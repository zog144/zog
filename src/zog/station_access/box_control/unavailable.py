from .port import BoxControlUnavailable

def create_gateway():
    raise BoxControlUnavailable(
        "station-access has no configured box-control adapter; set "
        "STATION_ACCESS_BOX_CONTROL_GATEWAY_FACTORY after mapping the current BoxControl inspection API"
    )
