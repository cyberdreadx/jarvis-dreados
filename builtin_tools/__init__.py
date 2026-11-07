"""DreadOS Tools: built-in, local, free tools the Assistant can call like any MCP service.

Each tool module exposes:
    TOOLS = [ {name, description, inputSchema}, ... ]   # MCP tool definitions
    def call(tool: str, arguments: dict) -> dict        # MCP result: {'content': [...], 'isError'?: bool}

Rules for every tool: pure Python standard library, no network, no shell, no file access,
deterministic, bounded input sizes, fast (well under a second), friendly error messages
returned as {'isError': True, 'content': [{'type': 'text', 'text': ...}]} instead of raising.
"""
import importlib

SERVICE_ID = 'dreados-tools'
SERVICE_NAME = 'DreadOS Tools'
# Module names inside this package, plus the original chord tool at the project root.
MODULES = ('calculate', 'charts', 'flowchart', 'qrcode_tool', 'palette', 'scales', 'site_templates', 'site_audit')

_registry = None


def _load():
    global _registry
    if _registry is None:
        registry, image_tools = {}, set()
        import chord_diagrams
        modules = [chord_diagrams]
        for name in MODULES:
            try:
                modules.append(importlib.import_module(f'{__name__}.{name}'))
            except ImportError:
                continue  # a tool that isn't built yet must not break the others
        for module in modules:
            for tool in getattr(module, 'TOOLS', None) or [getattr(module, 'TOOL')]:
                registry[tool['name']] = (tool, module)
                if tool.get('returnsImage', True) is not False:
                    image_tools.add(tool['name'])
        _registry = (registry, image_tools)
    return _registry


def tools():
    """Public MCP tool definitions (without internal keys)."""
    return [{k: v for k, v in tool.items() if k != 'returnsImage'} for tool, _ in _load()[0].values()]


def image_tools():
    return set(_load()[1])


def call(name, arguments):
    registry = _load()[0]
    if name not in registry:
        raise ValueError('Unknown DreadOS tool.')
    try:
        return registry[name][1].call(name, arguments)
    except Exception as error:  # a buggy tool reports an error instead of crashing the chat
        return error_result(f'{name} failed: {type(error).__name__}. Try simpler input.')


def error_result(message):
    return {'isError': True, 'content': [{'type': 'text', 'text': str(message)[:2000]}]}
