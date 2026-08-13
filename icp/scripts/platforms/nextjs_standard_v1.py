from platforms import inactive_platform_core_v1 as _core


def describe():
    return _core.describe_adapter(
        "nextjs", "nextjs-standard", activation_state="active", executable=True
    )


def verify_descriptor(document):
    _core.verify_adapter(
        document,
        "nextjs",
        "nextjs-standard",
        activation_state="active",
        executable=True,
    )
