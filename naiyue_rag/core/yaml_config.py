"""Shared bounded, strict YAML reading; schema and resource loading are callers' jobs."""
from pathlib import Path
import yaml
from yaml.events import AliasEvent
from .errors import SettingsError

MAX_SETTINGS_BYTES=65536


class StrictSettingsLoader(yaml.SafeLoader):
    def compose_node(self,parent,index):
        if self.check_event(AliasEvent):raise ValueError('invalid YAML structure')
        return super().compose_node(parent,index)

    def construct_mapping(self,node,deep=False):
        if not isinstance(node,yaml.MappingNode):raise ValueError('invalid YAML structure')
        result={}
        for key_node,value_node in node.value:
            if key_node.tag=='tag:yaml.org,2002:merge':raise ValueError('invalid YAML structure')
            key=self.construct_object(key_node,deep=deep)
            if type(key) is not str or key in result:raise ValueError('invalid YAML structure')
            result[key]=self.construct_object(value_node,deep=deep)
        return result


def read_yaml_mapping(path):
    try:
        source=Path(path).resolve()
        with source.open('rb') as handle:payload=handle.read(MAX_SETTINGS_BYTES+1)
    except (OSError,TypeError,ValueError,UnicodeError,RuntimeError):
        raise SettingsError('settings_file_error') from None
    if len(payload)>MAX_SETTINGS_BYTES:raise SettingsError('settings_too_large')
    try:data=yaml.load(payload.decode('utf-8'),Loader=StrictSettingsLoader)
    except (yaml.YAMLError,ValueError,UnicodeError,RecursionError):
        raise SettingsError('invalid_settings_yaml') from None
    return source,data
