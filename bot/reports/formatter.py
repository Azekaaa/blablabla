from datetime import datetime, timezone
from bot.services.analytics_service import CRMAnalytics
from bot.config import settings


def _fmt_money(amount: float, currency: str = "RUB") -> str:
    symbols = {"RUB": "₽", "USD": "$", "EUR": "€", "KZT": "₸", "UAH": "₴"}
    symbol = symbols.get(currency, currency)
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}М {symbol}"
    if amount >= 1_000:
        return f"{amount / 1_000:.0f}К {symbol}"
    return f"{amount:.0f} {symbol}"


def _deal_line(deal: dict, show_days: str = "inactive") -> str:
    title = deal["title"][:35] + ("..." if len(deal["title"]) > 35 else "")
    amount_str = _fmt_money(deal["amount"], deal.get("currency", "RUB"))
    manager = (deal.get("responsible") or "?")[:20]

    if show_days == "inactive" and deal.get("days_inactive"):
        days_label = f"🕐 {deal['days_inactive']}д без активности"
    elif show_days == "stage" and deal.get("days_in_stage"):
        days_label = f"🔒 {deal['days_in_stage']}д на этапе"
    else:
        days_label = ""

    stage_str = (deal.get("stage") or "")[:20]
    lines = [f"  • #{deal['id']} {title}"]
    lines.append(f"    {stage_str} | {amount_str} | {manager}")
    if days_label:
        lines.append(f"    {days_label}")
    return "\n".join(lines)


def build_full_report(analytics: CRMAnalytics) -> str:
    now_str = analytics.generated_at.astimezone().strftime("%d.%m.%Y %H:%M")
    currency = analytics.currency
    lines = []

    lines.append("📊 ОТЧЁТ CRM BITRIX24")
    lines.append(f"🕐 {now_str}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    lines.append("")
    lines.append("📋 СДЕЛКИ В РАБОТЕ")
    lines.append(f"📌 Всего сделок: {analytics.total_active_deals}")
    lines.append(f"💰 Общая сумма: {_fmt_money(analytics.total_active_amount, currency)}")

    lines.append("")
    lines.append("📅 СЕГОДНЯ")
    lines.append(f"🆕 Новых сделок: {analytics.new_deals_today}")
    lines.append(f"✅ Закрыто (успех): {analytics.won_deals_today}")
    lines.append(f"❌ Закрыто (провал): {analytics.lost_deals_today}")
    lines.append(f"📊 Всего закрыто: {analytics.closed_deals_today}")

    lines.append("")
    lines.append(f"⚠️ ПРОБЛЕМНЫЕ СДЕЛКИ ({analytics.total_problem_deals})")

    if analytics.inactive_deals:
        lines.append("")
        lines.append(f"🕐 Без активности >{settings.inactive_days_threshold}д ({len(analytics.inactive_deals)}):")
        for deal in analytics.inactive_deals[:5]:
            lines.append(_deal_line(deal, "inactive"))
        if len(analytics.inactive_deals) > 5:
            lines.append(f"  ...и ещё {len(analytics.inactive_deals) - 5} сделок")
    else:
        lines.append(f"🕐 Без активности >{settings.inactive_days_threshold}д: нет")

    if analytics.deals_without_tasks:
        lines.append("")
        lines.append(f"📋 Без задач ({len(analytics.deals_without_tasks)}):")
        for deal in analytics.deals_without_tasks[:5]:
            lines.append(_deal_line(deal, "none"))
        if len(analytics.deals_without_tasks) > 5:
            lines.append(f"  ...и ещё {len(analytics.deals_without_tasks) - 5} сделок")
    else:
        lines.append("📋 Без задач: нет")

    if analytics.stuck_stage_deals:
        lines.append("")
        lines.append(f"🔒 Застряли на этапе >{settings.stuck_stage_days_threshold}д ({len(analytics.stuck_stage_deals)}):")
        for deal in analytics.stuck_stage_deals[:5]:
            lines.append(_deal_line(deal, "stage"))
        if len(analytics.stuck_stage_deals) > 5:
            lines.append(f"  ...и ещё {len(analytics.stuck_stage_deals) - 5} сделок")
    else:
        lines.append(f"🔒 Застряли на этапе >{settings.stuck_stage_days_threshold}д: нет")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🏆 ТОП МЕНЕДЖЕРОВ")

    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    for i, ms in enumerate(analytics.manager_stats[:5]):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        amount_str = _fmt_money(ms.total_amount, currency)
        problem_str = f" ⚠️{ms.problem_count}" if ms.problem_count > 0 else ""
        lines.append(f"{medal} {ms.name}")
        lines.append(f"   📁 {ms.deal_count} сд | 💰 {amount_str}{problem_str}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📈 ПО ЭТАПАМ ВОРОНКИ")

    total_deals = analytics.total_active_deals or 1
    for ss in analytics.stage_stats[:8]:
        pct = ss.count / total_deals * 100
        lines.append(f"  {ss.stage_name}: {ss.count} ({pct:.0f}%) — {_fmt_money(ss.total_amount, currency)}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🤖 ВЫВОД")
    lines.append(_generate_conclusion(analytics))
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Обновлено: {now_str}")

    return "\n".join(lines)


def build_managers_report(analytics: CRMAnalytics) -> str:
    currency = analytics.currency
    lines = ["🏆 РЕЙТИНГ МЕНЕДЖЕРОВ", ""]

    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    for i, ms in enumerate(analytics.manager_stats):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        amount_str = _fmt_money(ms.total_amount, currency)
        avg_str = _fmt_money(ms.avg_amount, currency)
        problem_badge = f"⚠️ {ms.problem_count} проб." if ms.problem_count else "✅"
        lines.append(f"{medal} {ms.name}")
        lines.append(f"   📁 Сделок: {ms.deal_count}")
        lines.append(f"   💰 Сумма: {amount_str}")
        lines.append(f"   📊 Средняя: {avg_str}")
        lines.append(f"   🔍 Статус: {problem_badge}")
        lines.append("")

    return "\n".join(lines)


def build_problems_report(analytics: CRMAnalytics) -> str:
    lines = [f"⚠️ ПРОБЛЕМНЫЕ СДЕЛКИ", f"Всего: {analytics.total_problem_deals}", ""]

    if analytics.inactive_deals:
        lines.append(f"🕐 Без активности >{settings.inactive_days_threshold} дней:")
        for d in analytics.inactive_deals:
            lines.append(_deal_line(d, "inactive"))
        lines.append("")

    if analytics.deals_without_tasks:
        lines.append("📋 Без задач:")
        for d in analytics.deals_without_tasks:
            lines.append(_deal_line(d, "none"))
        lines.append("")

    if analytics.stuck_stage_deals:
        lines.append(f"🔒 Застряли на этапе >{settings.stuck_stage_days_threshold} дней:")
        for d in analytics.stuck_stage_deals:
            lines.append(_deal_line(d, "stage"))
        lines.append("")

    if not any([analytics.inactive_deals, analytics.deals_without_tasks, analytics.stuck_stage_deals]):
        lines.append("✅ Проблемных сделок не обнаружено!")

    return "\n".join(lines)


def build_stats_report(analytics: CRMAnalytics) -> str:
    currency = analytics.currency
    lines = ["📈 СТАТИСТИКА CRM", ""]

    lines.append(f"📌 Сделок в работе: {analytics.total_active_deals}")
    lines.append(f"💰 Общая сумма: {_fmt_money(analytics.total_active_amount, currency)}")
    lines.append("")
    lines.append("📅 Сегодня:")
    lines.append(f"  🆕 Новых: {analytics.new_deals_today}")
    lines.append(f"  ✅ Успешно закрыто: {analytics.won_deals_today}")
    lines.append(f"  ❌ Провалено: {analytics.lost_deals_today}")
    lines.append("")
    lines.append("🗂 По этапам воронки:")

    total = analytics.total_active_deals or 1
    for ss in analytics.stage_stats:
        pct = ss.count / total * 100
        lines.append(f"  {ss.stage_name}: {ss.count} ({pct:.0f}%) — {_fmt_money(ss.total_amount, currency)}")

    return "\n".join(lines)


def _generate_conclusion(analytics: CRMAnalytics) -> str:
    conclusions = []

    if analytics.total_problem_deals == 0:
        conclusions.append("Воронка в хорошем состоянии — проблемных сделок нет.")
    elif analytics.total_problem_deals <= 3:
        conclusions.append(f"Есть {analytics.total_problem_deals} проблемных сделки — требуют внимания.")
    else:
        conclusions.append(f"{analytics.total_problem_deals} проблемных сделок — необходимы срочные действия!")

    if analytics.new_deals_today > 0:
        conclusions.append(f"Сегодня добавлено {analytics.new_deals_today} новых сделок.")

    if analytics.won_deals_today > 0:
        conclusions.append(f"Сегодня закрыто успешно: {analytics.won_deals_today} сделок.")

    if len(analytics.deals_without_tasks) > 5:
        conclusions.append(f"{len(analytics.deals_without_tasks)} сделок без задач — риск потери клиентов.")

    if analytics.manager_stats:
        top = analytics.manager_stats[0]
        conclusions.append(f"Лидер: {top.name} — {_fmt_money(top.total_amount, analytics.currency)} в работе.")

    return " ".join(conclusions) if conclusions else "Данных для анализа недостаточно."