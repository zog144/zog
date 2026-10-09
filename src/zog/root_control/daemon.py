import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from pathlib import Path

from .privileged import mount, unmount
from .protocol import decode, encode
from .systemd import BusctlSystemdBackend
from .build import BuildBackend
from .events import emit
from zog.box_control.errors import PersistenceError

DEFAULT_SOCKET = Path("/run/zog/root-control.sock")


class RootControlDaemon:
    def __init__(self, socket_path, *, systemd_backend=None, journal_barrier=None):
        self.socket_path = Path(socket_path)
        self.systemd = systemd_backend or BusctlSystemdBackend()
        self.build = BuildBackend(self.systemd, journal_barrier=journal_barrier)

    def serve(self):
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o660)
            server.listen(16)
            # Inspection readers never use the shared systemd backend/job connection.
            with ThreadPoolExecutor(max_workers=1) as mutations, ThreadPoolExecutor(max_workers=2) as logs:
                workers = (mutations, logs)
                slots = (BoundedSemaphore(8), BoundedSemaphore(2))
                while True:
                    conn, _ = server.accept()
                    try:
                        request = decode(conn, deadline=time.monotonic() + 10.0)
                        self._dispatch(conn, request, workers, slots)
                    except Exception as exc:
                        with conn:
                            self._respond(conn, {"ok": False, "error": str(exc)})

    @staticmethod
    def _respond(conn, response, *, operation=None, resource_id=None):
        try:
            conn.settimeout(5.0)
            conn.sendall(encode(response))
        except OSError:
            emit("root-control-response-undelivered", operation=operation, resource_id=resource_id)

    def _dispatch(self, conn, request, workers, slots):
        lane = 1 if request.get('operation') in {'application_logs', 'build_job_logs', 'application_processes', 'build_job_processes', 'workspace_verify', 'build_registration_status'} else 0
        if not slots[lane].acquire(blocking=False):
            with conn:
                self._respond(conn, {"ok": False, "error": "root-control lane busy; retry later"})
            return
        try:
            workers[lane].submit(self._serve_request, conn, request, slots[lane], time.monotonic())
        except BaseException:
            slots[lane].release()
            conn.close()
            raise

    def _serve_request(self, conn, request, slot, queued_at=None):
        started = time.monotonic()
        registration = request.get('operation') == 'build_register'
        rid = request.get('resource_id')
        # Do not echo arbitrary client strings into diagnostics.
        rid = rid if isinstance(rid, str) and len(rid) == 32 and all(c in '0123456789abcdef' for c in rid) else None
        if registration:
            emit('build-registration-start', resource_id=rid,
                 queued_seconds=started-(queued_at if queued_at is not None else started))
        try:
            with conn:
                try:
                    response = self.handle(request)
                except Exception as exc:
                    response = {"ok": False, "error": str(exc), "storage_failure": isinstance(exc, PersistenceError), "code": getattr(exc, "code", None)}
                if registration:
                    emit('build-registration-finish', resource_id=rid, ok=response.get('ok') is True,
                         elapsed_seconds=time.monotonic()-started)
                self._respond(conn, response, operation='build_register' if registration else None, resource_id=rid)
        finally:
            slot.release()

    def handle(self, request):
        operation = request.get("operation")
        if operation in {"build_register", "build_prepare", "build_start", "build_observe", "build_cleanup", "build_cancel", "build_release", "build_forget"}:
            arguments = {k:v for k,v in request.items() if k != "operation"}
            return {"ok": True, "result": getattr(self.build, operation[6:])(**arguments)}
        if operation in {"application_processes", "build_job_processes"}:
            from .processes import inspect
            allowed = ({"project_root", "runtime_id", "program", "limit"} if operation == "application_processes"
                       else {"project_root", "job_id", "limit"})
            arguments = {k:v for k,v in request.items() if k != "operation"}
            if not set(arguments) <= allowed:
                raise ValueError("unsupported process inspection arguments")
            return {"ok": True, "result": inspect(**arguments)}
        if operation == 'build_registration_status':
            return {'ok': True, 'result': self.build.registration_status(
                project_root=request['project_root'], resource_id=request['resource_id'])}
        if operation == "build_job_logs":
            from .journal import read_build_logs
            return {"ok": True, "result": read_build_logs(**{k:v for k,v in request.items() if k != "operation"})}
        if operation == "application_logs":
            from .journal import read_logs
            return {"ok": True, "result": read_logs(**{k:v for k,v in request.items() if k != "operation"})}
        if operation == "ping":
            return {"ok": True}
        if operation == "mount":
            mount(
                request["source"], request["target"], request["filesystem"],
                int(request.get("flags", 0)), request.get("data")
            )
            return {"ok": True}
        if operation == "unmount":
            unmount(request["target"], int(request.get("flags", 0)))
            return {"ok": True}
        if operation == "application_storage_sync":
            self.systemd.sync_application_storage(project_root=request['project_root'],
                application=request['application'], storage_id=request['storage_id'])
            return {"ok": True, "result": None}
        if operation == "application_storage_delete":
            self.systemd.delete_application_storage(project_root=request['project_root'],
                application=request['application'], storage_id=request['storage_id'])
            return {"ok": True, "result": None}
        if operation in {'workspace_prepare', 'workspace_verify'}:
            from .workspace import WorkspaceBackend
            backend = WorkspaceBackend(BusctlSystemdBackend() if operation == 'workspace_verify' else self.systemd)
            return {"ok": True, "result": getattr(backend, operation[10:])(**{k:v for k,v in request.items() if k != 'operation'})}
        if operation == "systemd_version":
            return {"ok": True, "result": self.systemd.version()}
        if operation == "systemd_start_slice":
            self.systemd.start_slice(
                project_root=request["project_root"],
                slice_name=request["slice_name"],
                description=request["description"],
            )
            return {"ok": True}
        if operation == "systemd_start_service":
            self.systemd.start_service(
                project_root=request["project_root"],
                generation=request["generation"],
                definition=request["definition"],
            )
            return {"ok": True}
        if operation == "systemd_observe":
            result = self.systemd.observe(
                project_root=request["project_root"], unit_name=request["unit_name"]
            )
            return {"ok": True, "result": result}
        if operation == "systemd_kill":
            self.systemd.kill(
                project_root=request["project_root"],
                unit_name=request["unit_name"],
                signal_number=int(request["signal_number"]),
            )
            return {"ok": True}
        if operation == "systemd_stop":
            self.systemd.stop(
                project_root=request["project_root"], unit_name=request["unit_name"]
            )
            return {"ok": True}
        if operation == "systemd_release":
            self.systemd.release(project_root=request["project_root"], unit_name=request["unit_name"])
            return {"ok": True}
        if operation == "systemd_reset_failed":
            self.systemd.reset_failed(
                project_root=request["project_root"], unit_name=request["unit_name"]
            )
            return {"ok": True}
        raise ValueError(f"unsupported operation: {operation!r}")


def main():
    # Environment override is for root-control deployment/testing only. The
    # box-control public API itself has no environment-variable configuration.
    socket_path = os.environ.get("ROOT_CONTROL_SOCKET", str(DEFAULT_SOCKET))
    barrier = None
    if os.environ.get('ROOT_CONTROL_JOURNAL_BARRIER') == '1':
        from .journal_barrier import JournalBarrier
        barrier = JournalBarrier()
        barrier.start()
    RootControlDaemon(socket_path, journal_barrier=barrier).serve()


if __name__ == "__main__":
    main()
