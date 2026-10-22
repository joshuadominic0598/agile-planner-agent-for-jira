"""Descriptive assignee profiles from the current export, never delivery history."""

from collections import Counter

from . import analytics, recency


def insights(assigned, counted, finished):
    work = counted(assigned)
    points = [row['points'] for row in work if row.get('points') is not None]
    buckets = [
        {'name': 'Below 3 points', 'count': sum(value < 3 for value in points)},
        {'name': '3 to below 5 points', 'count': sum(3 <= value < 5 for value in points)},
        {'name': '5 points and above', 'count': sum(value >= 5 for value in points)},
    ]
    maximum = max((bucket['count'] for bucket in buckets), default=0)
    usual = [bucket['name'] for bucket in buckets if bucket['count'] == maximum and maximum]
    sprint_names = {sprint for row in assigned for sprint in row['sprints']}
    sprint_rows = []
    assigned_sprint_points = 0
    sprint_estimates = [row for row in work if row['sprints'] and row.get('points') is not None]
    for sprint in sorted(sprint_names, key=analytics.sprint_sort, reverse=True):
        members = analytics.select(assigned, sprint)
        counted_members = counted(members)
        assigned_sprint_points += sum(row.get('points') or 0 for row in counted_members)
        done = [row for row in counted_members if finished(row)]
        sprint_rows.append(
            {
                'sprint': sprint,
                'assigned_tickets': len(members),
                'finished_tickets': sum(finished(row) for row in members),
                'known_finished_points': round(sum(row.get('points') or 0 for row in done), 2),
                'finished_without_points': sum(row.get('points') is None for row in done),
            }
        )
    return {
        'average_points_per_sprint': round(assigned_sprint_points / len(sprint_names), 2)
        if sprint_names and sprint_estimates
        else None,
        'average_points_sprint_count': len(sprint_names),
        'sprint_point_unestimated_tickets': sum(
            bool(row['sprints']) and row.get('points') is None for row in work
        ),
        'assigned_total': len(assigned),
        'unfinished_total': sum(not finished(row) for row in assigned),
        'finished_total': sum(finished(row) for row in assigned),
        'point_estimated_tickets': len(points),
        'point_unestimated_tickets': sum(row.get('points') is None for row in work),
        'point_size_buckets': buckets,
        'usual_point_size': ' / '.join(usual) if usual else 'No story-point estimates',
        'common_point_sizes': [
            {'points': value, 'count': count} for value, count in Counter(points).most_common(3)
        ],
        'sprint_work': sprint_rows,
        'unscheduled_finished_tickets': sum(finished(row) and not row['sprints'] for row in assigned),
        'recent_work': [
            {key: row.get(key) for key in ('key', 'summary', 'status', 'points', 'updated', 'created')}
            for row in recency.latest(assigned, 5)
        ],
    }
