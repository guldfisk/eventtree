from __future__ import annotations

import typing as t
from abc import ABCMeta, abstractmethod

from eventdispatch.dispatcher import DispatchSession


T = t.TypeVar('T')


def _dict_merge(*dicts) -> t.Dict:
    result = {}
    for dictionary in dicts:
        result.update(dictionary)
    return result


class EventSession(object):

    def __init__(self):
        self._dispatch_session = DispatchSession()

        self._conditions: t.Set[Condition] = set()
        self._event_stack: t.List[Event] = []

        self._trigger_queue: t.List[Trigger] = []
        self._stack: t.List[Trigger] = []

        self._replacement_chooser: t.Type[Event] = ChooseReplacement

    @property
    def dispatcher(self) -> DispatchSession:
        return self._dispatch_session

    @property
    def trigger_queue(self) -> t.List[Trigger]:
        return self._trigger_queue

    def log_event(self, event: Event) -> None:
        self._event_stack.append(event)

    def event_finished(self, event: Event, success: bool) -> None:
        pass

    def get_time_stamp(self) -> int:
        return len(self._event_stack)

    def resolve_event(
        self,
        event_type: t.Type[Event],
        source: t.Optional[Event] = None,
        parent: t.Optional[Event] = None,
        **kwargs,
    ) -> t.Any:
        return event_type(session = self, source = source, parent = parent, **kwargs).resolve()

    def create_condition(
        self,
        condition_type: t.Type[Condition],
        parent: t.Optional[Event] = None,
        **kwargs,
    ) -> Condition:
        condition = condition_type(session = self, **kwargs)
        self.resolve_event(ConnectCondition, parent = parent, condition = condition)
        return condition

    def connect_condition(self, condition: Condition, parent: t.Optional[Event] = None) -> None:
        self.resolve_event(ConnectCondition, parent = parent, condition = condition)

    def disconnect_condition(self, condition: Condition, parent: t.Optional[Event] = None) -> None:
        self.resolve_event(DisconnectCondition, parent = parent, condition = condition)

    def choose_replacement(self, options: t.Sequence[Replacement]) -> Replacement:
        return self.resolve_event(
            self._replacement_chooser,
            options = options,
        )

    def resolve_reactions(self, event: Event, post: bool):
        pass


class SessionBound(object):

    def __init__(self, session: EventSession):
        self._session = session

    @property
    def session(self) -> session:
        return self._session


class Sourced(SessionBound):

    def __init__(self, session: EventSession, source: t.Any = None):
        super().__init__(session)
        self._source = source

    @property
    def source(self) -> t.Any:
        return self._source


class EventException(Exception):
    pass


class EventSetupException(EventException):
    pass


class EventCheckException(EventException):
    pass


class EventResolutionException(EventException):
    pass


class Event(Sourced, metaclass = ABCMeta):

    def __init__(
        self,
        session: EventSession,
        source: t.Any = None,
        parent: Event = None,
        replaced_by: t.Set[Replacement] = None,
        **kwargs,
    ):
        super().__init__(session, source)
        self._parent = parent
        if parent is not None:
            parent.children.append(self)

        self._replaced_by = set() if replaced_by is None else replaced_by
        self._values = kwargs

        self._children: t.List[Event] = []

    @property
    def children(self):
        return self._children

    @property
    def values(self) -> t.Mapping[str, t.Any]:
        return self._values

    @property
    def parent(self) -> t.Optional[Event]:
        return self._parent

    @abstractmethod
    def payload(self, **kwargs):
        pass

    def setup(self, **kwargs):
        pass

    def check(self, **kwargs):
        pass

    def resolve(self, **kwargs):
        self.setup(**kwargs)

        replacements = [
            value
            for connected, value in
            self._session.dispatcher.send(signal = '_try_' + self.__class__.__name__, source = self)
            if not value in self._replaced_by
        ]

        if replacements:
            choice = (
                self._session.choose_replacement(replacements)
                if len(replacements) > 1 else
                replacements[0]
            )
            self._replaced_by.add(choice)
            return choice.replace(self)

        self.check(**kwargs)

        self._session.log_event(self)
        self._session.resolve_reactions(self, False)

        self._session.dispatcher.send(signal = '_pre_respond_' + self.__class__.__name__, source = self)

        try:
            result = self.payload(**kwargs)
        except EventException:
            self._session.event_finished(self, False)
            raise

        self._session.event_finished(self, True)

        self._session.resolve_reactions(self, True)
        self._session.dispatcher.send(signal = self.__class__.__name__, source = self)

        return result

    def depend_tree(self, event_type: t.Type[Event], **kwargs):
        return event_type(
            session = self._session,
            source = self._source,
            parent = self,
            replaced_by = set(self._replaced_by),
            **_dict_merge(self._values, kwargs),
        ).resolve()

    def depend_branch(self, event_type: t.Type[Event], **kwargs):
        return event_type(
            session = self._session,
            source = self._source,
            parent = self,
            replaced_by = set(self._replaced_by),
            **kwargs,
        ).resolve()

    def replace(self, event_type: t.Type[Event], **kwargs):
        return event_type(
            session = self._session,
            source = self._source,
            parent = self._parent,
            replaced_by = set(self._replaced_by),
            **_dict_merge(self._values, kwargs),
        ).resolve()

    def replace_clone(self, **kwargs):
        return type(self)(
            session = self._session,
            source = self._source,
            parent = self._parent,
            replaced_by = set(self._replaced_by),
            **_dict_merge(self._values, kwargs),
        ).resolve()

    def spawn_tree(self, event_type: t.Type[Event], **kwargs):
        try:
            return event_type(
                session = self._session,
                source = self._source,
                parent = self,
                replaced_by = None,
                **_dict_merge(self._values, kwargs),
            ).resolve()
        except EventException:
            return None

    def branch(self, event_type: t.Type[Event], **kwargs):
        try:
            return event_type(
                session = self._session,
                source = self._source,
                parent = self,
                replaced_by = None,
                **kwargs,
            ).resolve()
        except EventException:
            return None


class Condition(Sourced):
    trigger: str = ''

    def __init__(self, session, source: t.Any = None, **kwargs):
        super().__init__(session, source)
        self.trigger = kwargs.get('trigger', self.trigger)
        self.successful_load = kwargs.get('successful_load', self.successful_load)
        self.condition = kwargs.get('condition', self.condition)
        self.time_stamp = -1

    def get_trigger(self, **kwargs) -> str:
        return self.trigger

    def condition(self, source: t.Any, **kwargs) -> bool:
        return True

    def load(self, source: t.Optional[Event] = None, **kwargs) -> t.Any:
        if self.condition(source, **kwargs):
            return self.successful_load(source)

    def successful_load(self, source: t.Optional[Event] = None) -> t.Any:
        pass

    def _connect(self) -> None:
        self.time_stamp = self._session.get_time_stamp()
        # self._session._conditions.add(self.condition)
        self._session.dispatcher.connect(self.load, signal = self.get_trigger())

    def _disconnect(self) -> None:
        self._session.dispatcher.disconnect(self.load, signal = self.get_trigger())
        # self._session._conditions.discard(self.condition)


class ChooseReplacement(Event):

    @property
    def options(self) -> t.Sequence[Replacement]:
        return self._values['options']

    def payload(self, **kwargs):
        return sorted(self.options, key = lambda replacement: replacement.time_stamp)[0]


class ConnectCondition(Event):

    @property
    def condition(self) -> Condition:
        return self._values['condition']

    @condition.setter
    def condition(self, condition: Condition):
        self._values['condition'] = condition

    def payload(self, **kwargs):
        self.condition._connect()


class DisconnectCondition(Event):

    @property
    def condition(self) -> Condition:
        return self._values['condition']

    @condition.setter
    def condition(self, condition: Condition):
        self._values['condition'] = condition

    def payload(self, **kwargs):
        self.condition._disconnect()


class Replacement(Condition):

    def __init__(self, session, source: t.Any = None, **kwargs):
        super().__init__(session, source, **kwargs)
        self._replace = kwargs.get('replace', self._replace)

    def get_trigger(self) -> str:
        return '_try_' + self.trigger

    def successful_load(self, source: t.Optional[t.Any] = None) -> Replacement:
        return self

    def _replace(self, event: Event) -> None:
        pass

    def replace(self, event: Event) -> None:
        self._replace(event)


class Reaction(Condition):

    def __init__(self, session, source: t.Any = None, **kwargs):
        super().__init__(session, source, **kwargs)
        self.react = kwargs.get('react', self.react)

    def get_trigger(self):
        return '_react_' + self.trigger

    def successful_load(self, source: t.Optional[t.Any] = None):
        return self

    def react(self, event: Event):
        pass


class PostReaction(Reaction):

    def get_trigger(self):
        return '_post_react_' + self.trigger


class Triggered(Event):
    name = 'triggered'

    @property
    def trigger(self) -> Trigger:
        return self._values['trigger']

    def payload(self, **kwargs):
        self._session.trigger_queue.append(
            self.trigger
        )


class Trigger(Condition):

    def __init__(self, session, source: t.Any = None, **kwargs):
        super().__init__(session, source, **kwargs)
        self.resolve = kwargs.get('resolve', self.resolve)

    def successful_load(self, source: t.Optional[t.Any] = None):
        self._session.resolve_event(
            Triggered,
            parent = source,
            trigger = self,
        )

    def resolve(self, source: t.Optional[Event] = None):
        pass


class Response(Condition):

    def __init__(self, session, source: t.Any = None, **kwargs):
        super().__init__(session, source, **kwargs)
        self.resolve = kwargs.get('resolve', self.resolve)

    def successful_load(self, source: t.Optional[Event] = None):
        self.resolve(source)

    def resolve(self, source: t.Optional[Event] = None):
        pass


class PreResponse(Response):

    def get_trigger(self, **kwargs):
        return '_pre_respond_' + self.trigger


class Continuous(Condition):
    terminate_trigger = ''

    def __init__(self, session, **kwargs):
        super(Continuous, self).__init__(session, **kwargs)
        self.terminateTrigger = kwargs.get('terminate_trigger', self.terminate_trigger)
        self.terminate_condition = kwargs.get('terminate_condition', self.terminate_condition)

    def get_terminate_trigger(self):
        return self.terminateTrigger

    def terminate_condition(self, **kwargs):
        return True

    def terminate(self, source, **kwargs):
        if self.terminate_condition():
            self._disconnect()

    def _connect(self):
        super(Continuous, self)._connect()
        self._session.dispatcher.connect(self.terminate, signal = self.get_terminate_trigger())

    def _disconnect(self):
        super(Continuous, self)._disconnect()
        self._session.dispatcher.disconnect(self.terminate, signal = self.get_terminate_trigger())


class ContinuousReplacement(Continuous, Replacement):
    pass


class DelayedTrigger(Trigger):
    name = 'BaseDelayedTrigger'

    def successful_load(self, source: t.Optional[t.Any] = None):
        super().successful_load(source)
        self._session.disconnect_condition(self, parent = source)


class DelayedMixin(object):
    _session: EventSession
    _replace: t.Callable

    def replace(self, event: Event):
        self._session.disconnect_condition(self, parent = event.parent)
        self._replace(event)


class DelayedReplacement(DelayedMixin, Replacement):
    name = 'BaseDelayedReplacement'


class ContinuousDelayedReplacement(DelayedMixin, ContinuousReplacement):
    name = 'BaseContinuousDelayedReplacement'


class SingleAttemptReplacement(Replacement):
    name = 'base_single_attempt_replacement'

    def successful_load(self, source: t.Optional[t.Any] = None):
        self._disconnect()
        return super().successful_load(source)


class StaticAttributeModification(t.Generic[T], Condition):
    trigger = ''

    def get_trigger(self, **kwargs):
        return '_aa_' + self.trigger

    def condition(self, source: t.Any, owner: t.Any, value: T, **kwargs) -> bool:
        return True

    def resolve(self, owner: S, value: T) -> T:
        return value

    def successful_load(self, parent: t.Optional[Event] = None):
        return self


S = t.TypeVar('S', bound = SessionBound)


class EventProperty(property):

    def __init__(
        self,
        getter: t.Callable[[S], T],
        setter: t.Optional[t.Callable[[S, T], None]] = None,
        deleter: t.Optional[t.Callable[[S], None]] = None,
        doc: t.Optional[str] = None,
        name: t.Optional[str] = None,
    ) -> None:
        self._name = getter.__name__ if name is None else name
        super().__init__(self._getter_wrapper(getter), setter, deleter, doc)

    def _getter_wrapper(self, getter: t.Callable[[S], T]):
        def _wrapped(owner: S):
            base_value = getter(owner)
            for response in sorted(
                [
                    value
                    for connected, value in
                    owner.session.dispatcher.send(
                        '_aa_' + self._name,
                        owner = owner,
                        value = base_value,
                    )
                ],
                key = lambda modification: modification.time_stamp,
            ):
                if response is not None:
                    base_value = response.resolve(owner, base_value)
            return base_value
        return _wrapped

