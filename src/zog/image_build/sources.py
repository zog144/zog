import os
import posixpath
import shutil
import tarfile
from pathlib import Path
from .errors import ImageBuildError
from .filesystem import digest
from .source_acquisition import acquire
from .metadata import relative


def stage(package, destination, cache, *, source_mirror=None):
    destination, cache = Path(destination), Path(cache)
    destination.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    acquisitions = []
    for source in package.sources:
        bundled = None
        if source["url"].startswith("recipe:"):
            if not package.recipe_directory:
                raise ImageBuildError("recipe source has no definition directory")
            root = Path(package.recipe_directory).resolve()
            bundled = root / relative(source["url"][7:])
            if (bundled.is_symlink() or not bundled.resolve().is_relative_to(root)
                    or not bundled.is_file() or digest(bundled) != source["sha256"]):
                raise ImageBuildError("bundled recipe source missing, unsafe or changed")
        payload, acquisition = acquire(
            source, cache, bundled=bundled, source_mirror=source_mirror
        )
        acquisitions.append(acquisition)
        target = destination / relative(source["destination"])
        if source["archive"]:
            target.mkdir(parents=True)
            with tarfile.open(payload) as archive:
                # Validate the complete archive before writing. Links are created
                # last, never traversed while extracting members.
                members = archive.getmembers()
                seen = set()
                for member in members:
                    name = member.name.rstrip("/")
                    if name in ("", "."):
                        continue
                    relative(name)
                    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()) or name in seen:
                        raise ImageBuildError(
                            f"unsupported/duplicate archive entry: {member.name}"
                        )
                    seen.add(name)
                links = {m.name.rstrip('/') for m in members if m.issym() or m.islnk()}
                by_name = {m.name.rstrip('/'): m for m in members}
                resolved_links = {}
                for member in members:
                    name = member.name.rstrip('/')
                    if any(parent.as_posix() in links for parent in Path(name).parents):
                        raise ImageBuildError('archive member descends through a link')
                    if member.issym() or member.islnk():
                        current = member
                        visited = set()
                        while current.issym() or current.islnk():
                            current_name = current.name.rstrip('/')
                            if current_name in visited:
                                raise ImageBuildError('cyclic archive link')
                            visited.add(current_name)
                            if current.linkname.startswith('/'):
                                raise ImageBuildError('absolute archive link')
                            resolved = posixpath.normpath(
                                posixpath.join(posixpath.dirname(current_name), current.linkname)
                                if current.issym() else current.linkname)
                            relative(resolved)
                            if any(parent.as_posix() in links for parent in Path(resolved).parents):
                                raise ImageBuildError('archive link must name a regular member or directory')
                            current = by_name.get(resolved)
                            if current is None:
                                # Source test fixtures may contain dangling symlinks.
                                # Their normalized target is contained and cannot
                                # traverse another archive link. Hard links still
                                # require an existing regular-file endpoint.
                                break
                        if member.islnk() and (current is None or not current.isfile()):
                            raise ImageBuildError('archive hard link must name a regular member')
                        resolved_links[name] = resolved
                for member in members:
                    name = member.name.rstrip("/")
                    if name in ("", "."):
                        continue
                    path = target / name
                    if member.issym() or member.islnk():
                        continue
                    if member.isdir():
                        path.mkdir(parents=True, exist_ok=True)
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as stream, path.open(
                            "xb"
                        ) as output:
                            shutil.copyfileobj(stream, output)
                        path.chmod(member.mode & 0o777)
                        # Release archives carry generated configure/Makefile files.
                        # Preserve timestamps so make does not regenerate them
                        # based on extraction order.
                        os.utime(path, (member.mtime, member.mtime))
                for member in members:
                    path = target / member.name.rstrip('/')
                    if member.issym():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        resolved = resolved_links[member.name.rstrip('/')]
                        path.symlink_to(posixpath.relpath(resolved, posixpath.dirname(member.name)))
                    elif member.islnk():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target / resolved_links[member.name.rstrip('/')], path)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(payload, target)
    return acquisitions
