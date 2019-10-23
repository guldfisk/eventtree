
from eventtree.replaceevent import *

class DealDamage(Event):

    @property
    def amount(self) -> int:
        return self._values['amount']

    @amount.setter
    def amount(self, amount: int) -> None:
        self._values['amount'] = amount

    damage_dealt = 0

    def payload(self, **kwargs):
        DealDamage.damage_dealt += self.amount
        print('Dealt {} damage! ({} total)'.format(self.amount, self.damage_dealt))


class DoubleDamage(DelayedReplacement):
    trigger = 'DealDamage'

    def _replace(self, event: DealDamage):
        # super().replace(event)
        event.replace_clone(amount=event.amount*2)


class IncreaseDamage(Replacement):
    trigger = 'DealDamage'

    def _replace(self, event: DealDamage):
        # super().replace(event)
        event.replace_clone(amount=event.amount + 1)


class BonusDamage(Trigger):
    trigger = 'DealDamage'

    def resolve(self, source: t.Optional[Event] = None, **kwargs):
        source.spawn_tree(DealDamage, amount=2)


class MoreExpensive(StaticAttributeModification):
    trigger = 'price'

    def resolve(self, owner: 'ProtectedAttribute', value: t.Any, **kwargs):
        return value + 1


class Free(StaticAttributeModification):
    trigger = 'price'

    def resolve(self, owner: 'ProtectedAttribute', value: t.Any, **kwargs):
        return 0


class Card(Attributed):

    def __init__(self, session: EventSession):
        super().__init__(session)
        self.price = self.pa('price', 10)


def test():

    session = EventSession()

    # session.dispatcher.connect(lambda print)

    # session.create_condition(IncreaseDamage)
    session.create_condition(DoubleDamage)
    session.create_condition(IncreaseDamage)

    # session.create_condition(DoubleDamage)
    # session.create_condition(DoubleDamage)

    session.create_condition(BonusDamage)
    #
    session.create_condition(MoreExpensive)
    # session.create_condition(Free)

    card = Card(session)

    session.resolve_event(DealDamage, amount=card.price.get())
    session.resolve_event(DealDamage, amount=card.price.get())
    session.resolve_event(DealDamage, amount=1)

    # session.resolve_triggers()
    # session.resolve_triggers()


if __name__ == '__main__':
    test()
