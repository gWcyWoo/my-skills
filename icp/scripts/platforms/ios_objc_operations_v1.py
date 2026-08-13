from platforms import controlled_platform_operations_v1 as _core


def list_operation_ids():
    return _core.list_operation_ids("ios-objc")


def build(operation_id, request):
    return _core.build_plan("ios-objc", "ios-objc-standard", operation_id, request)


def verify_plan(plan):
    return _core.verify_plan("ios-objc", "ios-objc-standard", plan)
