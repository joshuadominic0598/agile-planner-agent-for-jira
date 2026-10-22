import { useRef, useState } from 'react';
import People from './People';
import type { Split } from './types';

export type PlanningPerson = {
  name: string;
  roles: string[];
  eligible: boolean;
  active: boolean;
  developer: boolean;
  available: boolean;
  unit: 'points' | 'hours';
  budget: number | null;
  known_load: number | null;
  missing_estimates: number;
  headroom: number | null;
  typical_types: Split;
  assigned_total: number;
  unfinished_total: number;
  finished_total: number;
  point_estimated_tickets: number;
  point_unestimated_tickets: number;
  average_points_per_sprint: number | null;
  average_points_sprint_count: number;
  sprint_point_unestimated_tickets: number;
  usual_point_size: string;
  point_size_buckets: Split;
  common_point_sizes: { points: number; count: number }[];
  sprint_work: {
    sprint: string;
    assigned_tickets: number;
    finished_tickets: number;
    known_finished_points: number;
    finished_without_points: number;
  }[];
  recent_work: { key: string; summary: string; status: string; points: number | null }[];
};

export default function BacklogPeople({
  people,
  onTicket,
  base,
  project,
  onPeopleSaved,
}: {
  people: PlanningPerson[];
  onTicket: (key: string) => void;
  base: string;
  project: string;
  onPeopleSaved: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const manageButton = useRef<HTMLButtonElement>(null);
  const developers = people.filter((person) => person.developer);
  const shown = developers.length ? developers : people;
  return (
    <section className="card planning-people" aria-label="People & planning">
      <div className="card-heading">
        <div>
          <h2>People & planning</h2>
          <p className="muted small">Roles, average sprint points and typical tickets across this project.</p>
        </div>
        <button
          ref={manageButton}
          className="button secondary"
          aria-expanded={editing}
          onClick={() => {
            setEditing(!editing);
            setSaved(false);
          }}>
          {editing ? 'Cancel editing' : 'Manage people'}
        </button>
      </div>
      {!developers.length && (
        <p className="muted small">
          No developers marked yet. Use Manage people to choose developers and their work areas.
        </p>
      )}
      {editing && (
        <People
          base={base}
          project={project}
          sprint=""
          editorOnly
          onSaved={async () => {
            await onPeopleSaved();
            setEditing(false);
            setSaved(true);
            manageButton.current?.focus({ preventScroll: true });
          }}
        />
      )}
      {saved && (
        <p className="planning-saved" role="status">
          People profiles saved · Planning report updated.
        </p>
      )}
      <p className="muted small">
        Averages use known assigned points and exported sprint membership. Missing estimates make them
        partial; a ticket in multiple sprints counts in each.
      </p>
      <div className="planning-people-list">
        {shown.map((person) => (
          <article className="planning-person" key={person.name}>
            <div className="planning-person-heading">
              <div>
                <h3>{person.name}</h3>
                <p className="small muted">
                  {person.roles.join(' · ') || 'Work areas not configured'} ·{' '}
                  {!person.active
                    ? 'Inactive'
                    : person.developer
                      ? 'Active developer'
                      : 'Developer role not confirmed'}
                </p>
              </div>
              <span className="subtle-tag">
                {person.assigned_total} assigned · {person.unfinished_total} unfinished
              </span>
            </div>
            <div className="planning-person-facts">
              <div>
                <h4>Typical tickets</h4>
                <p>
                  {person.typical_types
                    .slice(0, 3)
                    .map((type) => `${type.name} (${type.count})`)
                    .join(' · ') || 'No assigned tickets'}
                </p>
              </div>
              <div className="planning-person-average">
                <h4>Avg. points per sprint</h4>
                <p>
                  {person.average_points_per_sprint === null
                    ? 'Not available'
                    : person.average_points_per_sprint.toLocaleString(undefined, {
                        maximumFractionDigits: 2,
                      })}
                </p>
                <small className="muted">
                  {person.average_points_sprint_count} sprint
                  {person.average_points_sprint_count === 1 ? '' : 's'}
                  {person.sprint_point_unestimated_tickets > 0 &&
                    ` · ${person.sprint_point_unestimated_tickets} ticket${person.sprint_point_unestimated_tickets === 1 ? '' : 's'} without points`}
                </small>
              </div>
            </div>
            <details className="planning-person-details">
              <summary>Story sizes & recent work</summary>
              {person.recent_work.slice(0, 5).map((ticket) => (
                <p className="small" key={ticket.key}>
                  <button className="issue-key" onClick={() => onTicket(ticket.key)}>
                    {ticket.key}
                  </button>{' '}
                  · {ticket.summary}{' '}
                  <span className="muted">
                    ·{' '}
                    {ticket.points === null || ticket.points === undefined
                      ? 'No point estimate'
                      : `${ticket.points} pts`}{' '}
                    · {ticket.status}
                  </span>
                </p>
              ))}
            </details>
          </article>
        ))}
      </div>
      {!shown.length && <p>No people found in this project.</p>}
    </section>
  );
}
