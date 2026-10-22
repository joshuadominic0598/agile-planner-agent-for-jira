"""Snapshot metrics share exactly the same classifier as issue filtering."""
import re
from collections import Counter

from . import workflow


def split(issues, field):
    return [{"name": k, "count": v} for k, v in Counter(i[field] or "Unspecified" for i in issues).most_common()]


def metrics(issues):
    assignees = {i['assignee'] for i in issues if i['assignee']}
    reporters = {i['reporter'] for i in issues if i['reporter']}
    return {
        "total": len(issues),
        'assignee_count': len(assignees),
        'reporter_count': len(reporters),
        'people_count': len(assignees | reporters),
        "unassigned": sum(not i["assignee"] for i in issues),
        "story_points": round(sum(i["points"] or 0 for i in issues), 2),
        "estimated_issues": sum(i["points"] is not None for i in issues),
        'original_hours': round(sum(i.get('original_seconds') or 0 for i in issues) / 3600, 2),
        'remaining_hours': round(sum(i.get('remaining_seconds') or 0 for i in issues) / 3600, 2),
        'spent_hours': round(sum(i.get('spent_seconds') or 0 for i in issues) / 3600, 2),
        'time_estimated_issues': sum(i.get('original_seconds') is not None for i in issues),
        'remaining_time_issues': sum(i.get('remaining_seconds') is not None for i in issues),
        'spent_time_issues': sum(i.get('spent_seconds') is not None for i in issues),
        'resolution_set_issues': sum(bool(i.get('resolution')) for i in issues),
        'parent_issues': sum(bool(i.get('is_parent')) for i in issues),
        'child_issues': sum(bool(i.get('has_parent')) for i in issues),
    }


def category_counts(issues, universe=None):
    counts = Counter(i['category'] for i in issues)
    names = dict.fromkeys(i['category'] for i in (universe if universe is not None else issues))
    return [{'id': workflow.stage_id('category:' + name), 'label': name or 'Not provided', 'count': counts[name], 'statuses': []} for name in names]


def resolution_counts(issues):
    counts = Counter(i.get('resolution') or '' for i in issues)
    return [{'id': workflow.stage_id('resolution:' + name), 'label': name or 'Not provided (blank)', 'count': count, 'statuses': []} for name, count in counts.most_common()]


def sprint_sort(name):
    return [(1, int(t)) if t.isdigit() else (0, t.casefold()) for t in re.split(r"(\d+)", name)]


def select(issues, sprint=None):
    if sprint == "__unscheduled__":
        return [i for i in issues if not i["sprints"]]
    return [i for i in issues if sprint in i["sprints"]] if sprint else issues


def dashboard(issues, sprint=None, configs=None):
    configs = configs if configs is not None else workflow.resolve(issues)
    status_order = list(dict.fromkeys(s for config in configs.values() for s in config['order']))
    def status_split(rows):
        counts = Counter(i['status'] for i in rows)
        return [{'name': name, 'count': counts[name]} for name in status_order if counts[name]]
    sprint_counts = Counter(s for i in issues for s in i["sprints"])
    sprints = sorted(sprint_counts, key=sprint_sort, reverse=True)
    selected = select(issues, sprint)
    return {
        "overall": metrics(issues), "categories": category_counts(issues), "stages": workflow.stage_counts(issues, configs), "statuses": status_split(issues), "types": split(issues, "type"),
        "workflow": {"configured_projects": sum(c['configured'] for c in configs.values()), "project_count": len(configs), "customized_projects": sum(c['customized'] for c in configs.values())},
        "sprints": [{"name": s, "count": sprint_counts[s]} for s in sprints],
        "suggested_sprint": sprints[0] if sprints else None,
        "sprint": {"name": sprint, "metrics": metrics(selected), 'resolutions': resolution_counts(selected), "categories": category_counts(selected, issues), "stages": workflow.stage_counts(selected, configs), "priorities": split(selected, "priority"), "types": split(selected, "type"), "statuses": status_split(selected)},
    }
