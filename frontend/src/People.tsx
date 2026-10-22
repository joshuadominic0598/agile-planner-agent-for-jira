import { useEffect, useRef, useState } from 'react';
import { api, params } from './api';
import { TypeBadge } from './IssueIdentity';
import type { Split } from './types';
import RoleChart from './RoleChart';

type Person = {
  project: string;
  assignee: string;
  work_areas: string[];
  is_developer: boolean;
  is_active: boolean;
  total: number;
  selected_total: number;
  types: Split;
  selected_types: Split;
};
type Team = {
  assigned_people: number;
  selected_people: number;
  developer_count: number;
  other_member_count: number;
  inactive_member_count: number;
  unassigned_issues: number;
  work_areas: Split;
  people: Person[];
};
export default function People({
  base,
  project,
  sprint,
  editorOnly = false,
  onSaved,
}: {
  base: string;
  project: string;
  sprint: string;
  editorOnly?: boolean;
  onSaved?: () => void | Promise<void>;
}) {
  const [team, setTeam] = useState<Team | null>(null);
  const [drafts, setDrafts] = useState<
    Record<string, { areas: string; developer: boolean; active: boolean }>
  >({});
  const [membership, setMembership] = useState('all');
  const [roleFilter, setRoleFilter] = useState('');
  const [editing, setEditing] = useState(editorOnly);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [retry, setRetry] = useState(0);
  const manageButton = useRef<HTMLButtonElement>(null);
  const key = (p: Person) => JSON.stringify([p.project, p.assignee]);
  useEffect(() => {
    let live = true;
    setTeam(null);
    setError('');
    api<Team>(`${base}/people?${params({ project, sprint })}`)
      .then((result) => {
        if (live) {
          setTeam(result);
          setDrafts(
            Object.fromEntries(
              result.people.map((p) => [
                key(p),
                { areas: p.work_areas.join(', '), developer: p.is_developer, active: p.is_active },
              ])
            )
          );
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [base, project, sprint, retry]);
  useEffect(() => {
    if (saved && !editing && !saving) {
      manageButton.current?.focus({ preventScroll: true });
      manageButton.current?.scrollIntoView({ block: 'nearest' });
    }
  }, [saved, editing, saving]);
  function change(person: Person, change: Partial<{ areas: string; developer: boolean; active: boolean }>) {
    setDrafts((existing) => ({ ...existing, [key(person)]: { ...existing[key(person)], ...change } }));
    setSaved(false);
  }
  async function save() {
    if (!team || saving) return;
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      await api(`${base}/people`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          people: team.people.map((p) => ({
            project: p.project,
            assignee: p.assignee,
            work_areas: drafts[key(p)].areas
              .split(',')
              .map((a) => a.trim())
              .filter(Boolean),
            is_developer: drafts[key(p)].developer,
            is_active: drafts[key(p)].active,
          })),
        }),
      });
      setEditing(false);
      setSaved(true);
      try {
        const result = await api<Team>(`${base}/people?${params({ project, sprint })}`);
        setTeam(result);
        setDrafts(
          Object.fromEntries(
            result.people.map((p) => [
              key(p),
              { areas: p.work_areas.join(', '), developer: p.is_developer, active: p.is_active },
            ])
          )
        );
      } catch (e) {
        setError(`Profiles saved, but the updated counts could not be loaded. ${(e as Error).message}`);
      }
      await onSaved?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  const visiblePeople =
    team?.people.filter(
      (p) =>
        (membership === 'all' || drafts[key(p)]?.active === (membership === 'active')) &&
        (!roleFilter ||
          drafts[key(p)]?.areas
            .split(',')
            .map((a) => a.trim())
            .includes(roleFilter))
    ) || [];
  return (
    <section
      className="people-section"
      aria-label={editorOnly ? 'Manage planning people' : 'People and work'}>
      {!editorOnly && (
        <div className="section-heading">
          <div>
            <span className="eyebrow">THE PEOPLE BEHIND THE WORK</span>
            <h2>People & work</h2>
          </div>
          <button
            ref={manageButton}
            className="button secondary"
            disabled={saving}
            aria-expanded={editing}
            onClick={() => setEditing((v) => !v)}>
            {editing ? 'Hide people' : 'Manage people'}
          </button>
        </div>
      )}
      {error && (
        <div className="error" role="alert">
          {error}{' '}
          <button className="text-button" onClick={() => setRetry((r) => r + 1)}>
            Reload people
          </button>
        </div>
      )}
      {!team && !error && <p role="status">Loading people…</p>}
      {team && (
        <>
          {!editorOnly && (
            <>
              <div className="people-metrics project-people-metrics">
                <article className="card">
                  <span>People assigned</span>
                  <strong>{team.assigned_people}</strong>
                  <small>Includes historical assignees</small>
                </article>
                <article className="card">
                  <span>Active Developers</span>
                  <strong>{team.developer_count}</strong>
                  <small>Active people marked as developers</small>
                </article>
                <article className="card">
                  <span>Other Members</span>
                  <strong>{team.other_member_count}</strong>
                  <small>Active people not marked as developers</small>
                </article>
                <article className="card">
                  <span>Inactive Members</span>
                  <strong>{team.inactive_member_count}</strong>
                  <small>Marked inactive by you</small>
                </article>
              </div>
              {!!team.inactive_member_count && (
                <p className="membership-note">
                  Historical tickets and sprint people counts still include inactive members.
                </p>
              )}
              {!!team.work_areas.length && (
                <RoleChart
                  data={team.work_areas}
                  description="Distinct people in each assigned role, including active and inactive members. Select a bar to see matching people. A person with several roles appears once in each."
                  onSelect={(role) => {
                    setEditing(true);
                    setMembership('all');
                    setRoleFilter(role);
                  }}
                />
              )}
            </>
          )}
          {editing && (
            <div className="card people-editor">
              <p className="card-subtitle">
                Ticket types describe observed work across this project snapshot. Add your own work-area
                labels, separated by commas, and mark developers explicitly. Mark former team members inactive
                to keep their historical tickets while excluding them from active team counts. You can
                reactivate them later. Changes are saved per project; absence from a sprint does not
                automatically mark someone inactive.
              </p>
              <fieldset disabled={saving}>
                <legend className="sr-only">People profiles</legend>
                <label className="membership-filter">
                  <span>SHOW PEOPLE</span>
                  <select
                    aria-label="Filter people by membership"
                    value={membership}
                    onChange={(e) => setMembership(e.target.value)}>
                    <option value="all">All members</option>
                    <option value="active">Active members</option>
                    <option value="inactive">Inactive members</option>
                  </select>
                </label>
                <label className="membership-filter">
                  <span>ROLE</span>
                  <select
                    aria-label="Filter people by role"
                    value={roleFilter}
                    onChange={(e) => setRoleFilter(e.target.value)}>
                    <option value="">All roles</option>
                    {team.work_areas.map((r) => (
                      <option key={r.name} value={r.name}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="people-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>PERSON</th>
                        <th>TICKET TYPE MIX · PROJECT</th>
                        <th>WORK AREAS</th>
                        <th>DEVELOPER</th>
                        <th>MEMBERSHIP</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visiblePeople.map((p) => (
                        <tr key={key(p)}>
                          <td>
                            <strong>{p.assignee}</strong>
                            {!drafts[key(p)]?.active && (
                              <span className="inactive-member-badge">Inactive</span>
                            )}
                            <small>
                              {p.project} · {p.total} assigned issues
                            </small>
                          </td>
                          <td>
                            <div className="person-types">
                              {p.types.map((t) => (
                                <span key={t.name}>
                                  <TypeBadge name={t.name} /> <b>{t.count}</b>
                                </span>
                              ))}
                            </div>
                          </td>
                          <td>
                            <input
                              aria-label={`Work areas for ${p.assignee} in ${p.project}`}
                              list="work-area-suggestions"
                              placeholder="Backend, Lead…"
                              value={drafts[key(p)]?.areas || ''}
                              onChange={(e) => change(p, { areas: e.target.value })}
                            />
                          </td>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`Developer ${p.assignee} in ${p.project}`}
                              checked={drafts[key(p)]?.developer || false}
                              onChange={(e) => change(p, { developer: e.target.checked })}
                            />
                          </td>
                          <td>
                            <select
                              aria-label={`Membership for ${p.assignee} in ${p.project}`}
                              value={drafts[key(p)]?.active ? 'active' : 'inactive'}
                              onChange={(e) => change(p, { active: e.target.value === 'active' })}>
                              <option value="active">Active</option>
                              <option value="inactive">Inactive</option>
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!!team.people.length && !visiblePeople.length && (
                    <p className="muted membership-empty">
                      No people match these membership and role filters.
                    </p>
                  )}
                </div>
                <datalist id="work-area-suggestions">
                  {['Data', 'AI', 'DevOps', 'Backend', 'Frontend', 'Lead', 'Manager', 'Product Owner'].map(
                    (area) => (
                      <option key={area} value={area} />
                    )
                  )}
                </datalist>
                <div className="workflow-actions">
                  <span>
                    {team.unassigned_issues} issues are unassigned in this project view. Counts reflect
                    assignments at export time, not team capacity.
                  </span>
                  <button
                    className="button primary"
                    disabled={!team.people.length}
                    onClick={() => void save()}>
                    {saving ? 'Saving…' : 'Save people profiles'}
                  </button>
                </div>
              </fieldset>
              {!team.people.length && (
                <p className="muted">
                  No assignees found. Include the Assignee column in your next Jira export.
                </p>
              )}
            </div>
          )}
        </>
      )}
      {saved && <p role="status">People profiles saved.</p>}
    </section>
  );
}
