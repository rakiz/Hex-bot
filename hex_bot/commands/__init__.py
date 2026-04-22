# Import command modules here so their @register_command decorators execute
from .tasks import TasksCommand  # noqa: F401
from .register import RegisterCommand  # noqa: F401
from .unregister import UnregisterCommand  # noqa: F401
from .status import StatusCommand  # noqa: F401