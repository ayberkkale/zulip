from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from psycopg2.sql import SQL

from analytics.views.activity_common import (
    fix_rows,
    format_date_for_activity_reports,
    format_none_as_zero,
    get_query_data,
    make_table,
    remote_installation_stats_link,
    remote_installation_support_link,
)
from corporate.lib.analytics import get_plan_data_by_remote_server
from corporate.lib.stripe import cents_to_dollar_string
from zerver.decorator import require_server_admin
from zilencer.models import get_remote_server_guest_and_non_guest_count


@require_server_admin
def get_remote_server_activity(request: HttpRequest) -> HttpResponse:
    title = "Remote servers"

    query = SQL(
        """
        with mobile_push_forwarded_count as (
            select
                server_id,
                sum(coalesce(value, 0)) as push_forwarded_count
            from zilencer_remoteinstallationcount
            where
                property = 'mobile_pushes_forwarded::day'
                and end_time >= current_timestamp(0) - interval '7 days'
            group by server_id
        ),
        remote_push_devices as (
            select
                server_id,
                count(distinct(user_id, user_uuid)) as push_user_count
            from zilencer_remotepushdevicetoken
            group by server_id
        )
        select
            rserver.id,
            rserver.hostname,
            rserver.contact_email,
            rserver.last_version,
            rserver.last_audit_log_update,
            push_user_count,
            push_forwarded_count
        from zilencer_remotezulipserver rserver
        left join mobile_push_forwarded_count on mobile_push_forwarded_count.server_id = rserver.id
        left join remote_push_devices on remote_push_devices.server_id = rserver.id
        where not deactivated
        order by push_user_count DESC NULLS LAST
    """
    )

    cols = [
        "ID",
        "Hostname",
        "Contact email",
        "Zulip version",
        "Last audit log update",
        "Mobile users",
        "Mobile pushes forwarded",
        "Plan name",
        "Plan status",
        "ARR",
        "Non guest users",
        "Guest users",
        "Links",
    ]

    # If the column order above changes, update the constants below
    SERVER_ID = 0
    SERVER_HOSTNAME = 1
    LAST_AUDIT_LOG_DATE = 4
    MOBILE_USER_COUNT = 5
    MOBILE_PUSH_COUNT = 6

    rows = get_query_data(query)
    total_row = []
    plan_data_by_remote_server = get_plan_data_by_remote_server()

    for row in rows:
        # Add estimated revenue for server
        server_plan_data = plan_data_by_remote_server.get(row[SERVER_ID])
        if server_plan_data is None:
            row.append("---")
            row.append("---")
            row.append("---")
        else:
            revenue = cents_to_dollar_string(server_plan_data.annual_revenue)
            row.append(server_plan_data.current_plan_name)
            row.append(server_plan_data.current_status)
            row.append(f"${revenue}")
        # Add user counts
        remote_server_counts = get_remote_server_guest_and_non_guest_count(row[SERVER_ID])
        row.append(remote_server_counts.non_guest_user_count)
        row.append(remote_server_counts.guest_user_count)
        # Add links
        stats = remote_installation_stats_link(row[SERVER_ID])
        support = remote_installation_support_link(row[SERVER_HOSTNAME])
        links = stats + " " + support
        row.append(links)
    # Format column data and add total row
    for i, col in enumerate(cols):
        if i == LAST_AUDIT_LOG_DATE:
            fix_rows(rows, i, format_date_for_activity_reports)
        if i in [MOBILE_USER_COUNT, MOBILE_PUSH_COUNT]:
            fix_rows(rows, i, format_none_as_zero)
        if i == SERVER_ID:
            total_row.append("Total")
        elif i in [MOBILE_USER_COUNT, MOBILE_PUSH_COUNT]:
            total_row.append(str(sum(row[i] for row in rows if row[i] is not None)))
        else:
            total_row.append("")
    rows.insert(0, total_row)

    content = make_table(title, cols, rows)
    return render(
        request,
        "analytics/activity_details_template.html",
        context=dict(data=content, title=title, is_home=False),
    )
