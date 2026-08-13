from platforms import inactive_platform_core_v1 as _core


def describe():
    return _core.describe_adapter("android-kotlin", "android-kotlin-standard", activation_state="active", executable=True)


def verify_descriptor(document):
    _core.verify_adapter(document, "android-kotlin", "android-kotlin-standard", activation_state="active", executable=True)
