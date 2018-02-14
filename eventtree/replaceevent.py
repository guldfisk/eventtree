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

		self._trigger_queue = [] #type: t.List[_TriggerPack]
		self._stack = [] #type: t.List[_TriggerPack]

		self._replacement_chooser = ChooseReplacement #type: t.Type[Event]
		self._trigger_orderer = OrderTriggers #type: t.Type[Event]

	@property
	def dispatcher(self):
		return self._dispatch_session

	def get_time_stamp(self):
		return len(self._event_stack)

	def resolve_event(self, event_type: 't.Type[Event]', **kwargs) -> t.Any:
		return event_type(session=self, **kwargs).resolve()

	def create_condition(self, condition_type: 't.Type[Condition]', **kwargs):
		self.resolve_event(ConnectCondition, condition=condition_type(session=self, **kwargs))

	def connect_condition(self, condition: 'Condition'):
		self.resolve_event(ConnectCondition, condition=condition)

	def disconnect_condition(self, condition: 'Condition'):
		self.resolve_event(DisconnectCondition, condition=condition)

	def resolve_triggers(self):
		self.resolve_event(ResolveTriggers)

	def choose_replacement(self, options: 't.Sequence[Replacement]') -> 'Replacement':
		return self.resolve_event(
			self._replacement_chooser,
			options=options,
		)

	def _order_triggers(self):
		self.resolve_event(
			self._trigger_orderer,
			triggers=self._trigger_queue,
		)


class SessionBound(object):
	def __init__(self, session: EventSession):
		self.session = session

class Sourced(SessionBound):
	def __init__(self, session: EventSession, source: t.Any = None):
		super().__init__(session)
		self.source = source

class EventSetupException(Exception):
	pass


class EventCheckException(Exception):
	pass


class Event(Sourced, metaclass=ABCMeta):
	name = 'base_event'

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

	@abstractmethod
	def payload(self, **kwargs):
		pass

	def setup(self, **kwargs):
		pass

	def check(self, **kwargs):
		pass

	def resolve(self, **kwargs):
		self.session._event_stack.append(self)
		try:
			self.setup(**kwargs)
		except EventSetupException:
			return
		replacements = [
			value
			for connected, value in
			self.session.dispatcher.send(signal='_try_' + self.name, **self.__dict__)
			if not value in self._replaced_by
		]
		if replacements:
			choice = (
				self.session.choose_replacement(replacements)
				if len(replacements) > 1 else
				replacements[0]
			)
			self._replaced_by.add(choice)
			return choice.replace(self)
		try:
			self.check(**kwargs)
		except EventCheckException:
			return
		result = self.payload(**kwargs)
		self.session.dispatcher.send(self.name, **self.__dict__)
		return result

	def spawn(self, event_type: 't.Type[Event]', **kwargs):
		return event_type(
				session = self.session,
				source = self.source,
				parent = self,
				replaced_by = set(self._replaced_by),
				**_dict_merge(self._values, kwargs),
			)

	def spawn_clone(self, **kwargs):
		return type(self)(
				session = self.session,
				source = self.source,
				parent = self,
				replaced_by = set(self._replaced_by),
				**_dict_merge(self._values, kwargs),
			)

	def spawn_tree(self, event_type: 't.Type[Event]', **kwargs):
		return event_type(
				session = self.session,
				source = self.source,
				parent = self,
				replaced_by = None,
				**_dict_merge(self._values, kwargs),
			)


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

	def condition(self, **kwargs):
		return True

	def load(self, signal, **kwargs):
		if self.condition(**kwargs):
			return self.successful_load(**kwargs)

	def successful_load(self, **kwargs):
		pass

	def connect(self):
		self.time_stamp = self.session.get_time_stamp()
		self.session._conditions.add(self.condition)
		self.session.dispatcher.connect(self.load, signal=self.get_trigger())

	def disconnect(self):
		self.session.dispatcher.disconnect(self.load, signal=self.get_trigger())
		self.session._conditions.discard(self.condition)


class ChooseReplacement(Event):
	name = 'choose_replacement'

	@property
	def options(self) -> 't.Sequence[Replacement]':
		return self._values['options']

	def payload(self, **kwargs):
		return sorted(self.options, key=lambda replacement: replacement.time_stamp)[0]


class OrderTriggers(Event):
	name = 'order_triggers'

	@property
	def triggers(self) -> 't.List[_TriggerPack]':
		return self._values['triggers']

	def payload(self, **kwargs):
		pass


class ResolveTriggers(Event):
	name = 'resolve_triggers'

	def payload(self, **kwargs):
		self._triggers = list(self.session._trigger_queue)
		self._stack = list(self.session._stack)
		self.session._order_triggers()
		self.session._stack.extend(self.session._trigger_queue)
		self.session._trigger_queue[:] = []
		while self.session._stack:
			self.session._stack.pop().resolve()


class ConnectCondition(Event):
	name = 'connect_condition'

	@property
	def condition(self) -> 'Condition':
		return self._values['condition']

	@condition.setter
	def condition(self, condition: 'Condition'):
		self._values['condition'] = condition

	def payload(self, **kwargs):
		self.condition.connect()

	def undo(self):
		self.condition.disconnect()


class DisconnectCondition(Event):
	name = 'disconnect_condition'
	condition = None #type: Condition

	def payload(self, **kwargs):
		self.condition.disconnect()

	def undo(self):
		self.condition.disconnect()


class Replacement(Condition):
	def get_trigger(self, **kwargs):
		return '_try_' + self.trigger

	def successful_load(self, **kwargs):
		return self

	def replace(self, event: Event):
		pass


class _TriggerPack(object):

	def __init__(self, trigger, circumstance):
		self.trigger = trigger
		self.circumstance = circumstance

	def resolve(self):
		self.trigger.resolve(**self.circumstance)


class Triggered(Event):
	name = 'triggered'

	@property
	def circumstance(self) -> 't.Dict[str, t.Any]':
		return self._values['circumstance']

	def __init__(self, **kwargs):
		self.trigger = kwargs.pop('trigger', None)
		super(Triggered, self).__init__(**kwargs)

	def payload(self, **kwargs):
		self._trigger_pack = _TriggerPack(
				self.trigger,
				self.circumstance
			)
		self.session._trigger_queue.append(self._trigger_pack)

	def undo(self):
		self.session._trigger_queue.remove(self._trigger_pack)


class Trigger(Condition):
	def successful_load(self, **kwargs):
		self.session.resolve_event(
			Triggered,
			trigger=self,
			circumstance=kwargs
		)

	def resolve(self, **kwargs):
		pass


class Continuous(Condition):
	terminate_trigger = ''

	def __init__(self, session, **kwargs):
		super(Continuous, self).__init__(session, **kwargs)
		self.terminateTrigger = kwargs.get('terminate_trigger', self.terminate_trigger)
		self.terminate_condition = kwargs.get('terminate_condition', self.terminate_condition)

	def get_terminate_trigger(self):
		return self.terminateTrigger

	def terminate_condition(self):
		return True

	def terminate(self, **kwargs):
		if self.terminate_condition(**kwargs):
			self.disconnect(**kwargs)

	def connect(self):
		super(Continuous, self).connect()
		self.session.dispatcher.connect(self.terminate, signal=self.get_terminate_trigger())

	def disconnect(self, **kwargs):
		super(Continuous, self).disconnect()
		self.session.dispatcher.disconnect(self.terminate, signal=self.get_terminate_trigger())


class DelayedTrigger(Continuous, Trigger):
	name = 'BaseDelayedTrigger'

	def successful_load(self, **kwargs):
		super().successful_load(**kwargs)
		self.disconnect()

	def terminate_condition(self, **kwargs):
		return False

class DelayedReplacement(Continuous, Replacement):
	name = 'BaseDelayedReplacement'

	def replace(self, event: Event):
		self.disconnect()

	def terminate_condition(self, **kwargs):
		return False


class AttributeModifying(object):
	trigger = ''

	def get_trigger(self, **kwargs):
		return '_aa_' + self.trigger

	def resolve(self, value, **kwargs):
		return value

	def successful_load(self, **kwargs):
		return self


# class ADStatic(AttributeModifying, Condition):
# 	name = 'base_ad_static'


class StaticAttributeModification(AttributeModifying, Continuous):
	name = 'base_ad_continuous'


class ProtectedAttribute(object):
	def __init__(self, owner: SessionBound, name: str, value: t.Any):
		self._owner = owner
		self._name = name
		self._value = value

	def get(self, **kwargs):
		val = copy.copy(self._value)
		for response in sorted(
			[
				o[1]
				for o in
				self._owner.session.dispatcher.send(
					'_aa_' + self._name,
					owner = self._owner,
					value = self._value,
					**kwargs,
				)
			],
			key = lambda modification: modification.time_stamp,
		):
			if response is not None:
				val = response.resolve(val, **kwargs)
		return val

	def set(self, val):
		self._value = val


class Attributed(SessionBound):
	def pa(self, name: str, initial_value: t.Any):
		return ProtectedAttribute(self, name, initial_value)
