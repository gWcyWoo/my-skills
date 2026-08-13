from platforms import inactive_platform_core_v1 as _core


def preflight(project_root):
    return _core.preflight("android-java", "android-java-standard", project_root)


def inspect_entry_requirements(project_root):
    return _core.inspect_entry_requirements("android-java", "android-java-standard", project_root)
