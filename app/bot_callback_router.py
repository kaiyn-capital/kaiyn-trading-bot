from collections.abc import Awaitable, Callable
from dataclasses import dataclass

CallbackHandler = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class CallbackRoute:
    handler: CallbackHandler
    include_data: bool = False
    admin_only: bool = False


class CallbackRouter:
    """Dispatch exact and prefixed Telegram callback payloads."""

    def __init__(
        self,
        exact_routes: dict[str, CallbackRoute],
        prefix_routes: tuple[tuple[str, CallbackRoute], ...],
    ):
        self._exact_routes = exact_routes
        self._prefix_routes = prefix_routes

    def resolve(self, data: str | None) -> CallbackRoute | None:
        if not isinstance(data, str):
            return None

        exact_route = self._exact_routes.get(data)
        if exact_route:
            return exact_route

        for prefix, route in self._prefix_routes:
            if data.startswith(prefix):
                return route

        return None

    def is_admin_callback(self, data: str | None) -> bool:
        route = self.resolve(data)
        return bool(route and route.admin_only)

    async def dispatch(self, query, user, data: str | None) -> bool:
        route = self.resolve(data)
        if not route:
            return False

        if route.include_data:
            await route.handler(query, user, data)
        else:
            await route.handler(query, user)

        return True
