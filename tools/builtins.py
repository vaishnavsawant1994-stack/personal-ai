from tools import (
    advanced_control,
    automation,
    browser,
    computer,
    continuity,
    documents,
    files,
    memory_tools,
    notifications,
    proactive,
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
):
    files.register(registry)
    web.register(registry)
    system.register(registry)
    memory_tools.register(registry, memory, second_brain=second_brain)
    documents.register(registry, settings)
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
