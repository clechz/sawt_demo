"""Isolated contract tests. These do not measure model or live voice quality."""
import copy
import unittest

from sawt.conversation_requirements import collect_requirements


class FixtureMenu:
    """Small catalog adapter implementing the existing Menu read contract."""
    def __init__(self):
        self.item = {
            'name': 'مضغوط لحم', 'available': ['branch_a'],
            'groups': {
                'rice': {'name': 'الرز', 'min': 1, 'max': 1,
                         'options': {'b': {'name': 'بسمتي', 'name_en': 'Basmati', 'delta': 0}}},
                'extra': {'name': 'إضافات', 'min': 0, 'max': 1,
                          'options': {'s': {'name': 'سلطة', 'name_en': 'Salad', 'delta': 500}}},
            },
        }

    def get(self, item_id):
        if item_id != 'meat':
            raise ValueError('Unknown item')
        return self.item

    def validate_line(self, line, branch=None):
        item = self.get(line['item_id'])
        for gid, ids in line['options'].items():
            if gid not in item['groups'] or any(oid not in item['groups'][gid]['options'] for oid in ids):
                raise ValueError('Invalid option')
        return dict(line, available=(branch in item['available'] if branch else None))


def state():
    return {
        'revision': 7, 'order_id': None, 'service': None, 'branch': None,
        'location': None, 'delivery_details': {},
        'basket': [{'line_id': 'l1', 'item_id': 'meat', 'quantity': 3, 'options': {}, 'notes': ''}],
        'pending_choice': {'question': 'existing question', 'revision': 7},
        'quote': {'presented': True, 'revision': 7},
    }


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        self.menu, self.state = FixtureMenu(), state()

    def test_reports_data_not_a_question_or_confirmation_permission(self):
        result = collect_requirements(self.menu, self.state)
        self.assertEqual(set(result), {'revision', 'order_status', 'missing_options', 'fulfillment', 'unavailable_lines'})
        self.assertEqual(result['missing_options'][0]['group_id'], 'rice')
        self.assertEqual(result['fulfillment'], [{'field': 'service', 'allowed_values': ['delivery', 'pickup']}])

    def test_preserves_cart_revision_quote_and_pending_question(self):
        before = copy.deepcopy(self.state)
        collect_requirements(self.menu, self.state)
        self.assertEqual(self.state, before)

    def test_does_not_default_a_required_choice(self):
        collect_requirements(self.menu, self.state)
        self.assertEqual(self.state['basket'][0]['options'], {})

    def test_saved_choice_and_optional_extra_are_not_missing(self):
        self.state['basket'][0]['options'] = {'rice': ['b']}
        self.assertEqual(collect_requirements(self.menu, self.state)['missing_options'], [])

    def test_all_lines_are_reported_not_only_first_missing_choice(self):
        self.state['basket'].append(dict(copy.deepcopy(self.state['basket'][0]), line_id='l2'))
        self.assertEqual([x['line_id'] for x in collect_requirements(self.menu, self.state)['missing_options']], ['l1', 'l2'])

    def test_pickup_only_requires_branch(self):
        self.state['service'] = 'pickup'
        self.assertEqual(collect_requirements(self.menu, self.state)['fulfillment'], [{'field': 'branch'}])

    def test_partial_delivery_retains_known_fields(self):
        self.state.update(service='delivery', delivery_details={'city': 'الرياض', 'zone': 'النرجس'})
        self.assertEqual(collect_requirements(self.menu, self.state)['fulfillment'], [{'field': 'street'}, {'field': 'building'}])

    def test_complete_but_unvalidated_address_is_not_silently_accepted(self):
        self.state.update(service='delivery', delivery_details=dict.fromkeys(['city', 'zone', 'street', 'building'], 'known'))
        self.assertEqual(collect_requirements(self.menu, self.state)['fulfillment'], [{'field': 'service_area_validation'}])

    def test_unavailable_line_remains_in_cart(self):
        self.state.update(service='pickup', branch='branch_b')
        result = collect_requirements(self.menu, self.state)
        self.assertEqual(result['unavailable_lines'][0]['line_id'], 'l1')
        self.assertEqual(len(self.state['basket']), 1)

    def test_output_cannot_mutate_catalog(self):
        result = collect_requirements(self.menu, self.state)
        result['missing_options'][0]['allowed_options'][0]['name'] = 'changed'
        self.assertEqual(self.menu.item['groups']['rice']['options']['b']['name'], 'بسمتي')

    def test_invalid_option_remains_an_error(self):
        self.state['basket'][0]['options'] = {'rice': ['invented']}
        with self.assertRaises(ValueError):
            collect_requirements(self.menu, self.state)

    def test_confirmed_order_does_not_restart_draft_questions(self):
        self.state['order_id'] = 'order_1'
        result = collect_requirements(self.menu, self.state)
        self.assertEqual(result['order_status'], 'confirmed')
        self.assertEqual(result['missing_options'], [])
        self.assertEqual(result['fulfillment'], [])

    def test_delivery_branch_is_resolution_not_customer_selection(self):
        self.state.update(service='delivery', location={'city': 'known'})
        self.assertEqual(collect_requirements(self.menu, self.state)['fulfillment'], [{'field': 'delivery_branch_resolution'}])

    def test_complete_draft_does_not_imply_confirmation(self):
        self.state.update(service='pickup', branch='branch_a')
        self.state['basket'][0]['options'] = {'rice': ['b']}
        result = collect_requirements(self.menu, self.state)
        self.assertEqual(result['order_status'], 'draft')
        self.assertEqual(result['missing_options'], [])
        self.assertEqual(result['fulfillment'], [])
        self.assertIsNone(self.state['order_id'])


if __name__ == '__main__':
    unittest.main()
