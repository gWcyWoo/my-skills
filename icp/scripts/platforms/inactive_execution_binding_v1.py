class InactiveExecutionError(ValueError):
    pass


def prepare_binding(*args, **kwargs):
    raise InactiveExecutionError("platform package is inactive; binding is forbidden")


def verify_binding(*args, **kwargs):
    raise InactiveExecutionError("platform package is inactive; binding is forbidden")
