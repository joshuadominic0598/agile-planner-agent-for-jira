import type { CSSProperties } from 'react';
import { Bug, CircleDot, GitBranch, FolderKanban } from 'lucide-react';
import type { Issue } from './types';

const palette = ['#487b72', '#447bac', '#a36b30', '#8b5e9d', '#637d42', '#a45e79'];
export function typeColor(name: string) {
  const normalized = name.toLocaleLowerCase();
  const bug = /\b(bug|defect)\b/.test(normalized);
  return bug ? '#ba4d43' : normalized === 'epic' ? '#8055ad' : normalized === 'story' ? '#397c6d' : normalized === 'task' || normalized === 'sub-task' ? '#447bac' : palette[Array.from(name).reduce((v, c) => v + c.charCodeAt(0), 0) % palette.length];
}
export function TypeBadge({ name }: { name: string }) {
  const normalized = name.toLocaleLowerCase();
  const bug = /\b(bug|defect)\b/.test(normalized);
  const color = typeColor(name);
  const Icon = bug ? Bug : normalized === 'epic' ? FolderKanban : CircleDot;
  return <span className="type-badge" style={{ '--type-color': color, backgroundColor: `${color}0d`, borderColor: `${color}30` } as CSSProperties}><Icon size={12} />{name}</span>;
}
export function ParentBadge({ issue }: { issue: Issue }) {
  return issue.is_parent ? <span className="parent-badge" title="Direct child issues across the entire export"><GitBranch size={12} />Parent · {issue.child_count}</span> : null;
}
