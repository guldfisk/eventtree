
from eventtree.replaceevent import *

class DealDamage(Event):
	name = 'deal_damage'

	@property
	def amount(self) -> int:
		return self._values['amount']

	@amount.setter
	def amount(self, amount: int):
		self._values['amount'] = amount

	damage_dealt = 0

	def payload(self, **kwargs):
		DealDamage.damage_dealt += self.amount
		print('Dealt {} damage!'.format(self.amount))

class DoubleDamage(DelayedReplacement):
	trigger = 'deal_damage'

	def replace(self, event: DealDamage):
		super().replace(event)
		event.spawn_clone(amount = event.amount*2).resolve()

class BonusDamage(DelayedTrigger):
	trigger = 'deal_damage'

	def resolve(self, **kwargs):
		self.session.resolve_event(DealDamage, amount=2)


class MoreExpensive(StaticAttributeModification):
	trigger = 'price'

	def resolve(self, value, **kwargs):
		return value + 1

class Free(StaticAttributeModification):
	trigger = 'price'

	def resolve(self, value, **kwargs):
		return 0


class Card(Attributed):

	def __init__(self, session: EventSession):
		super().__init__(session)
		self.price = self.pa('price', 10)

def test():

	session = EventSession()

	# session.create_condition(DoubleDamage)
	# session.create_condition(DoubleDamage)
	session.create_condition(DoubleDamage)

	session.create_condition(BonusDamage)

	session.create_condition(MoreExpensive)
	# session.create_condition(Free)

	card = Card(session)

	session.resolve_event(DealDamage, amount=card.price.get())
	session.resolve_event(DealDamage, amount=card.price.get())
	session.resolve_event(DealDamage, amount=1)

	session.resolve_triggers()
	session.resolve_triggers()

	print(DealDamage.damage_dealt)

if __name__ == '__main__':
	test()