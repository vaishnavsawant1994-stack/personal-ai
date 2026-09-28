from tools import (
    advanced_control,
    automation,
    browser,
    computer,
    continuity,
    desktop_file,
    documents,
    files,
    integrations,
    google_read,
    google_write,
    memory_tools,
    notifications,
    proactive,
    recovery,
    reminders,
    screen,
    system,
    vision,
    web,
)


def register_builtin_tools(
    registry,
    memory,
    settings,
    *,
    models=None,
    automation_engine=None,
    apns=None,
    second_brain=None,
    events=None,
    proactive_engine=None,
    continuity_service=None,
    integration_adapters=None,
):
    # Some tests/embedded surfaces construct ToolRegistry with only autonomy
    # settings and supply the durable data directory here. Bind once, before
    # any W7 operator/recovery authority is initialized.
    registry.bind_data_root(settings.data_dir)
    files.register(registry, settings)
    desktop_file.register(registry, settings)
    # W7.6 recovery extends the W7.1 transaction database. Initialize it only
    # after W7.5 registration has created/recovered the authoritative W7.1 store.
    registry.ensure_recovery_authority()
    recovery.register(registry)
    integrations.register(registry, integration_adapters)
    google_read.register(registry, integration_adapters)
    google_write.register(registry, integration_adapters)
    web.register(registry)
    system.register(registry)
    memory_tools.register(registry, memory, second_brain=second_brain)
    documents.register(registry, settings)
    if not bool(getattr(settings, 'hosted_runtime', False)):
        screen.register(registry, settings.data_dir)
    reminders.register(registry, memory)
    browser.register(registry)
    advanced_control.register(registry, settings)
    capability_objects = {}
    if models is not None:
        vision.register(registry, models, settings)
        capability_objects['computer'] = computer.register(
            registry,
            models,
            settings,
            second_brain=second_brain,
            events=events,
        )
    if automation_engine is not None:
        automation.register(registry, automation_engine)
    if proactive_engine is not None:
        proactive.register(registry, proactive_engine)
    if continuity_service is not None:
        continuity.register(registry, continuity_service)
    if apns is not None:
        notifications.register(registry, apns)
    return capability_objects
