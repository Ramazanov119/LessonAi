from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
from services.subscription_service import remaining_days, subscriptions_csv

ALMATY = ZoneInfo('Asia/Almaty')
STATUS = {'active': 'Активна', 'expiring': 'Истекает', 'expired': 'Истекла',
          'suspended': 'Приостановлена', 'missing': 'Нет подписки', 'scheduled': 'Ещё не началась'}


def render_subscription_status(status, payment_instructions):
    if not status['enforced']:
        st.info('Система подписок в режиме подготовки. Текущий доступ сохранён.')
        return
    if not status['allowed']:
        st.error('Доступ ограничен: ' + STATUS.get(status['status'], 'Статус не подтверждён'))
        st.write('Дата окончания:', status.get('ends_at') or 'Не назначена')
        if status.get('reason'):
            st.write('Причина:', status['reason'])
        st.info(payment_instructions)
        return
    days = remaining_days(status)
    if days is not None and 0 < days <= 7:
        threshold = 1 if days <= 1 else 3 if days <= 3 else 7
        st.warning(f'Подписка заканчивается через {days} дн. (напоминание за {threshold} дн.). ' + payment_instructions)


def render_admin(service, status):
    # Revalidate on every rerun; SQL independently authorizes each RPC.
    if service.access()['is_admin'] is not True:
        st.error('Доступ только для администратора.')
        return
    st.subheader('Админ-панель · Подписки')
    users = service.users()
    columns = st.columns(5)
    metrics = [('Всего', len(users)), ('Активных', sum(u['status'] in ('active','expiring') for u in users)),
               ('Истекающих', sum(u['status']=='expiring' for u in users)),
               ('Истёкших', sum(u['status']=='expired' for u in users)),
               ('Приостановленных', sum(u['status']=='suspended' for u in users))]
    for col, (label, value) in zip(columns, metrics):
        col.metric(label, value)
    query = st.text_input('Поиск по ФИО или email').strip().casefold()
    college = st.selectbox('Колледж', ['Все'] + sorted({u['college'] for u in users if u['college']}))
    state = st.selectbox('Статус подписки', ['Все'] + list(STATUS), format_func=lambda x: STATUS.get(x,x))
    rows = [u for u in users if (not query or query in (u['full_name']+' '+u['email']).casefold())
            and (college=='Все' or college==u['college']) and (state=='Все' or state==u['status'])]
    st.dataframe(rows, use_container_width=True)
    st.download_button('Скачать CSV', subscriptions_csv(rows), 'subscriptions.csv', 'text/csv')
    if not rows:
        return
    selected = st.selectbox('Пользователь', [u['user_id'] for u in rows],
        format_func=lambda uid: next(f"{u['full_name']} · {u['email']}" for u in rows if u['user_id']==uid))
    user = next(u for u in rows if u['user_id']==selected)
    st.write('Окончание:', user['ends_at'] or 'Не назначено', '· Осталось дней:', user['days_left'])
    with st.form('subscription_' + selected):
        action = st.selectbox('Действие', ['extend', 'set_end', 'suspend', 'resume'],
            format_func=lambda x: {'extend':'Продлить', 'set_end':'Установить дату', 'suspend':'Приостановить', 'resume':'Возобновить'}[x])
        days = st.selectbox('Срок продления, дней', [7,30,90,365])
        end = st.date_input('Последний оплаченный день (Алматы)', value=datetime.now(ALMATY).date()+timedelta(days=30))
        plan = st.text_input('Тариф', value=user['plan'] or 'standard')
        reason = st.text_input('Причина / комментарий', value='')
        confirm = st.checkbox('Подтверждаю изменение доступа выбранного пользователя')
        submit = st.form_submit_button('Применить')
    if submit:
        if not confirm:
            st.warning('Подтвердите изменение.')
        elif action=='suspend' and selected==status['user_id']:
            st.error('Нельзя приостановить собственный административный аккаунт.')
        else:
            # Exclusive boundary at midnight following the selected paid day.
            finish = datetime.combine(end+timedelta(days=1), time.min, ALMATY).isoformat()
            service.change(selected, action, days=days, ends_at=finish, reason=reason, plan=plan)
            st.success('Подписка обновлена. Приостановка снимается отдельным действием «Возобновить».')
            st.rerun()
    with st.form('payment_' + selected, clear_on_submit=True):
        st.write('Подтверждение полученной оплаты (без автоматического продления)')
        amount = st.number_input('Сумма, ₸', min_value=0.01, value=1000.0, step=100.0)
        paid = st.date_input('Дата оплаты', value=datetime.now(ALMATY).date())
        method = st.text_input('Способ оплаты', value='Перевод')
        comment = st.text_input('Комментарий к оплате')
        confirmed = st.checkbox('Подтверждаю получение оплаты')
        record = st.form_submit_button('Записать оплату')
    if record:
        if confirmed:
            service.payment(selected, amount, datetime.combine(paid,time.min,ALMATY).isoformat(), method, comment)
            st.success('Оплата записана.')
        else:
            st.warning('Подтвердите получение оплаты.')
    st.write('История продлений, изменений и оплат')
    st.dataframe(service.history(selected), use_container_width=True)
