"""Verified, deliberately limited customer service for a simulated restaurant.

This demo has no payment processor, staff inbox, external order database,
real delivery tracking or real refund authority. Cases exist only in the
current conversation's persisted state, not in a real restaurant CRM.
"""
import copy
import uuid

# All business policies below are ABOUT THIS DEMO, not invented restaurant policies.
TOPICS = {
    'refund': 'النسخة التجريبية ما تنفذ استرجاع مبالغ، ولا تقدر تحدد أهلية الاسترجاع أو مدته. نقدر نسجل طلب مراجعة تجريبي فقط.',
    'wrong_order': 'النسخة التجريبية تقدر تسجل بلاغ عن طلب غلط أو صنف ناقص. ما تقدر ترسل بديل أو تتواصل مع فرع فعلي.',
    'delay': 'ما فيه ربط مباشر بحالة تجهيز الطلب أو المندوب. وقت التحضير الظاهر تقديري في المحاكاة، مو تتبع مباشر.',
    'food_quality': 'نقدر نسجل ملاحظة عن جودة الأكل في بلاغ تجريبي. ما فيه مراجعة فعلية من المطعم.',
    'payment': 'ما فيه دفع أو سحب أو استرجاع مالي فعلي في النسخة التجريبية. لا تطلب بيانات البطاقة.',
    'allergens': 'ما عندنا قائمة مكونات أو حساسية موثقة. ما نقدر نضمن سلامة أي طبق لشخص لديه حساسية.',
    'hours': 'أوقات الدوام الفعلية غير متوفرة في البيانات المقدمة. لا تخمن وقت فتح أو إغلاق الفرع.',
    'tracking': 'ما فيه تتبع حي لطلب أو مندوب. أرقام الطلبات التجريبية لا تمثل طلبات في مطعم فعلي.',
    'promotions': 'لا توجد عروض أو كوبونات موثقة في بيانات المحاكاة. لا تعد بخصومات.',
    'human': 'التحويل الفعلي إلى موظف أو الاتصال بالفرع غير متاح. التذكرة التجريبية ليست تحويل مكالمة أو وعد اتصال.',
    'other': 'جاوب فقط بالمعلومات الموثقة في القائمة والفروع وحالة الطلب الحالية. إذا ما فيه بيانات كافية، وضحها بشكل مختصر وقدّم بلاغاً تجريبياً عند طلب العميل.',
}

CATEGORIES = {
    'refund_request': 'طلب استرجاع',
    'wrong_order': 'طلب غير صحيح',
    'missing_item': 'صنف ناقص',
    'late_order': 'تأخر الطلب',
    'food_quality': 'جودة الأكل',
    'general_complaint': 'شكوى',
    'other': 'مشكلة أخرى',
}


def info(topic):
    if topic not in TOPICS:
        raise ValueError('موضوع غير معروف')
    return {
        'topic': topic,
        'verified_demo_fact': TOPICS[topic],
        'can_issue_real_refund': False,
        'can_transfer_to_real_staff': False,
        'can_check_external_order': False,
    }


def file_case(state, category, description, order_reference=''):
    if category not in CATEGORIES:
        raise ValueError('نوع البلاغ غير معروف')
    description = description.strip()
    order_reference = order_reference.strip()
    if not description or len(description) > 300:
        raise ValueError('اشرح المشكلة باختصار')
    if len(order_reference) > 64:
        raise ValueError('رقم الطلب طويل')
    cases = state.setdefault('support_cases', [])
    # Same customer repeating the exact issue must not file duplicate cases.
    from .domain import normalize
    existing = next((c for c in cases if c['category'] == category
                     and normalize(c['description']) == normalize(description)
                     and normalize(c.get('order_reference', '')) == normalize(order_reference)), None)
    if existing:
        case = existing
        repeated = True
    else:
        if len(cases) >= 10:
            raise ValueError('الحد الأقصى للبلاغات التجريبية في المكالمة')
        case = {
            'case_id': 'T-' + uuid.uuid4().hex[:8].upper(),
            'category': category,
            'description': description,
            'order_reference': order_reference,
            'reference_verified': bool(order_reference and order_reference == state.get('order_id')),
            'status': 'demo_logged',
            'real_refund_issued': False,
            'staff_reviewed': False,
        }
        cases.append(case)
        repeated = False
    label = CATEGORIES[category]
    if repeated:
        message = 'البلاغ التجريبي موجود من قبل، رقمه ' + case['case_id'] + '.'
    else:
        message = 'أعتذر عن اللي صار. سجلت لك بلاغ تجريبي بخصوص ' + label + '، ورقمه ' + case['case_id'] + '.'
    message += ' ما فيه استرجاع مالي أو مراجعة من موظف فعلي في هالتجربة.'
    return {'case': copy.deepcopy(case), 'duplicate': repeated, 'reply': message}


def case_status(state, case_id=''):
    cases = state.get('support_cases') or []
    case_id = case_id.strip().upper()
    if not case_id and len(cases) == 1:
        selected = cases[0]
    elif not case_id and len(cases) > 1:
        return {'found': False, 'reply': 'عندك أكثر من بلاغ تجريبي. وش رقم البلاغ اللي تقصده؟'}
    else:
        selected = next((c for c in cases if c['case_id'] == case_id), None)
    if selected is None:
        return {'found': False, 'reply': 'ما لقيت هالبلاغ في المكالمة الحالية. ما عندي وصول لبلاغات أو طلبات مطعم حقيقي.'}
    return {'found': True, 'case': copy.deepcopy(selected),
            'reply': 'البلاغ التجريبي رقم ' + selected['case_id'] + ' مسجّل، وما تمت مراجعته من موظف أو تنفيذ أي استرجاع.'}
