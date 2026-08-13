class InactiveExecutionError(ValueError):
    pass


def prepare_authorization(*args, **kwargs):
    raise InactiveExecutionError("platform package is inactive; authorization is forbidden")


def verify_authorization(*args, **kwargs):
    raise InactiveExecutionError("platform package is inactive; authorization is forbidden")
