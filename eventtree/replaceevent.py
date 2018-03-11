import copy
import typing as t
from abc import ABCMeta, abstractmethod

from eventdispatch.dispatcher import DispatchSession


def _dict_merge(*dicts) -> t.Dict:
	result = {}
	for dictionary in dicts:
		result.update(dictionary)
	return result


class EventSession(object):
	def __init__(self):
		self._dispatch_session = DispatchSession()

		self._conditions = set() #type: t.Set[Condition]
		self._event_stack = [] #type: t.List[Event]

		self._trigger_queue = [] #type: t.List[Trigger]
		self._stack = [] #type: t.List[Trigger]

		self._replacement_chooser = ChooseReplacement #type: t.Type[Event]
		# self._trigger_orderer = OrderTriggers #type: t.Type[Event]

	@property
	def dispatcher(self) -> DispatchSession:
		return self._dispatch_session

	@property
	def trigger_queue(self) -> 't.List[Trigger]':
		return self._trigger_queue

	def log_event(self, event: 'Event') -> None:
		self._event_stack.append(event)

	def get_time_stamp(self) -> int:
		return len(self._event_stack)

	def resolve_event(self, event_type: 't.Type[Event]', parent: t.Optional[t.Any] = None, **kwargs) -> t.Any:
		return event_type(session=self, parent=parent, **kwargs).resolve()

	def create_condition(self, condition_type: 't.Type[Condition]', parent: 't.Optional[Event]' = None, **kwargs) -> 'Condition':
		condition = condition_type(session=self, **kwargs)
		self.resolve_event(ConnectCondition, parent=parent, condition=condition)
		return condition

	def connect_condition(self, condition: 'Condition', parent: 't.Optional[Event]' = None) -> None:
		self.resolve_event(ConnectCondition, parent=parent, condition=condition)

	def disconnect_condition(self, condition: 'Condition', parent: 't.Optional[Event]' = None) -> None:
		self.resolve_event(DisconnectCondition, parent=parent, condition=condition)

	def choose_replacement(self, options: 't.Sequence[Replacement]') -> 'Replacement':
		return self.resolve_event(
			self._replacement_chooser,
			options=options,
		)

	# def _order_triggers(self, parent: 't.Optional[Event]' = None) -> None:
	# 	self.resolve_event(
	# 		self._trigger_orderer,
	# 		parent = parent,
	# 		triggers = self._trigger_queue,
	# 	)

	# def choose_reaction(self, reactions: 't.List[Reaction]') -> 't.Optional[Reaction]':
	# 	return None

	def resolve_reactions(self, event: 'Event', post: bool):
		pass

class SessionBound(object):
	def __init__(self, session: EventSession):
		self._session = session


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


class Event(Sourced, metaclass=ABCMeta):

	def __init__(
		self,
		session: EventSession,
		source: t.Any = None,
		parent: 'Event' = None,
		replaced_by: 't.Set[Replacement]' = None,
		**kwargs,
	):
		super().__init__(session, source)
		self._parent = parent
		if parent is not None:
			parent.children.append(self)

		self._replaced_by = set() if replaced_by is None else replaced_by
		self._values = kwargs

		self._children = []  # type: t.List[Event]

	@property
	def children(self):
		return self._children

	@property
	def values(self):
		return self._values

	@property
	def parent(self) -> 't.Optional[Event]':
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
			self._session.dispatcher.send(signal='_try_' + self.__class__.__name__, source=self)
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

		self._session.dispatcher.send(signal= '_pre_respond_' + self.__class__.__name__, source=self)

		result = self.payload(**kwargs)

		self._session.resolve_reactions(self, True)
		self._session.dispatcher.send(signal=self.__class__.__name__, source=self)

		return result

	def depend_tree(self, event_type: 't.Type[Event]', **kwargs):
		return event_type(
			session = self._session,
			source = self._source,
			parent = self,
			replaced_by = set(self._replaced_by),
			**_dict_merge(self._values, kwargs),
		).resolve()

	def depend_branch(self, event_type: 't.Type[Event]', **kwargs):
		return event_type(
			session = self._session,
			source = self._source,
			parent = self,
			replaced_by = set(self._replaced_by),
			**kwargs,
		).resolve()

	def replace(self, event_type: 't.Type[Event]', **kwargs):
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

	def spawn_tree(self, event_type: 't.Type[Event]', **kwargs):
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

	def branch(self, event_type: 't.Type[Event]', **kwargs):
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
	trigger = ''

	def __init__(self, session, source: t.Any=None, **kwargs):
		super().__init__(session, source)
		self.trigger = kwargs.get('trigger', self.trigger)
		self.successful_load = kwargs.get('successful_load', self.successful_load)
		self.condition = kwargs.get('condition', self.condition)
		self.time_stamp = -1

	def get_trigger(self, **kwargs):
		return self.trigger

	def condition(self, source: t.Optional[t.Any] = None):
		return True

	def load(self, source: t.Optional[Event] = None, **kwargs):
		if self.condition(source):
			return self.successful_load(source)

	def successful_load(self, source: t.Optional[Event] = None):
		pass

	def _connect(self):
		self.time_stamp = self._session.get_time_stamp()
		self._session._conditions.add(self.condition)
		self._session.dispatcher.connect(self.load, signal=self.get_trigger())

	def _disconnect(self):
		self._session.dispatcher.disconnect(self.load, signal=self.get_trigger())
		self._session._conditions.discard(self.condition)


class ChooseReplacement(Event):

	@property
	def options(self) -> 't.Sequence[Replacement]':
		return self._values['options']

	def payload(self, **kwargs):
		return sorted(self.options, key=lambda replacement: replacement.time_stamp)[0]


# class OrderTriggers(Event):
#
# 	@property
# 	def triggers(self) -> 't.List[TriggerPack]':
# 		return self._values['triggers']
#
# 	def payload(self, **kwargs):
# 		pass
#
#
# class ResolveTriggers(Event):
#
# 	def payload(self, **kwargs):
# 		self._triggers = list(self._session._trigger_queue)
# 		self._stack = list(self._session._stack)
# 		if not self._triggers:
# 			return
# 		self._session._order_triggers(parent=self)
# 		self._session._stack.extend(self._session._trigger_queue)
# 		self._session._trigger_queue[:] = []
# 		print(self._session._stack)
# 		while self._session._stack:
# 			pack = self._session._stack.pop()
# 			print(pack)
# 			pack.resolve(self)


class ConnectCondition(Event):

	@property
	def condition(self) -> 'Condition':
		return self._values['condition']

	@condition.setter
	def condition(self, condition: 'Condition'):
		self._values['condition'] = condition

	def payload(self, **kwargs):
		self.condition._connect()


class DisconnectCondition(Event):

	@property
	def condition(self) -> 'Condition':
		return self._values['condition']

	@condition.setter
	def condition(self, condition: 'Condition'):
		self._values['condition'] = condition

	def payload(self, **kwargs):
		self.condition._disconnect()


class Replacement(Condition):

	def __init__(self, session, source: t.Any = None, **kwargs):
		super().__init__(session, source, **kwargs)
		self._replace = kwargs.get('replace', self._replace)

	def get_trigger(self):
		return '_try_' + self.trigger

	def successful_load(self, source: t.Optional[t.Any] = None):
		return self

	def _replace(self, event: Event):
		pass

	def replace(self, event: Event):
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
	def trigger(self) -> 'Trigger':
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

	def terminate(self):
		if self.terminate_condition():
			self._disconnect()

	def _connect(self):
		super(Continuous, self)._connect()
		self._session.dispatcher.connect(self.terminate, signal=self.get_terminate_trigger())

	def _disconnect(self):
		super(Continuous, self)._disconnect()
		self._session.dispatcher.disconnect(self.terminate, signal=self.get_terminate_trigger())


class DelayedTrigger(Trigger):
	name = 'BaseDelayedTrigger'

	def successful_load(self, source: t.Optional[t.Any] = None):
		super().successful_load(source)
		self._session.disconnect_condition(self, parent=source)


class DelayedReplacement(Replacement):
	name = 'BaseDelayedReplacement'

	def replace(self, event: Event):
		self._session.disconnect_condition(self, parent=event.parent)
		self._replace(event)


class SingleAttemptReplacement(Replacement):
	name = 'base_single_attempt_replacement'

	def successful_load(self, source: t.Optional[t.Any] = None):
		self._disconnect()
		return super().successful_load(source)


class StaticAttributeModification(Continuous):
	name = 'base_ad_continuous'
	trigger = ''

	def get_trigger(self, **kwargs):
		return '_aa_' + self.trigger

	def resolve(self, owner: 'ProtectedAttribute', value: t.Any):
		return value

	def successful_load(self, parent: 't.Optional[Event]' = None):
		return self


class ProtectedAttribute(object):
	def __init__(self, owner: SessionBound, name: str, value: t.Any):
		self._owner = owner
		self._name = name
		self._value = value

	def get(self):
		_value = copy.copy(self._value)
		for response in sorted(
			[
				o[1]
				for o in
				self._owner._session.dispatcher.send(
					signal = '_aa_' + self._name,
					owner = self._owner,
					value = self._value,
				)
			],
			key = lambda modification: modification.time_stamp,
		):
			if response is not None:
				_value = response.resolve(self, _value)
		return _value

	def set(self, val):
		self._value = val

	@property
	def owner(self) -> SessionBound:
		return self._owner


class Attributed(SessionBound):
	def pa(self, name: str, initial_value: t.Any):
		return ProtectedAttribute(self, name, initial_value)
