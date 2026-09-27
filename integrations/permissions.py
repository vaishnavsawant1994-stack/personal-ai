from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class IntegrationPermission:
    integration:str; capability:str; effect:str
DEFAULT_PERMISSIONS={
 'gmail':{'read_mail':'read','send_mail':'external'},
 'calendar':{'read_events':'read','create_event':'external','update_event':'external','delete_event':'destructive'},
 'slack':{'read_messages':'read','send_message':'external'},
 'home_assistant':{'read_state':'read','call_service':'external'},
}
def effect_for(integration,capability):return DEFAULT_PERMISSIONS.get(integration,{}).get(capability,'external')
