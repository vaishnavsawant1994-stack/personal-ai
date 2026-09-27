from tools.registry import Tool,Risk

def register(registry,apns):
    def send(params):
        device_id=str(params.get('device_id','')).strip();title=str(params.get('title','Personal AI'));body=str(params.get('body',''))
        if not device_id:raise ValueError('device_id is required')
        if not body:raise ValueError('body is required')
        return apns.send_device(device_id,title,body,data=params.get('data') or {},badge=params.get('badge'),collapse_id=params.get('collapse_id')).as_dict()
    registry.register(Tool('notify_device','Send a push notification to a paired iPhone through APNs. Requires approval because it creates an external side effect.',send,Risk.EXTERNAL_SIDE_EFFECT))
