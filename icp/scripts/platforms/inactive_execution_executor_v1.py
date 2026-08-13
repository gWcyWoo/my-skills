class InactiveExecutionError(ValueError):
    pass


def execute_authorization(*args, **kwargs):
    raise InactiveExecutionError("platform package is inactive; execution is forbidden")
