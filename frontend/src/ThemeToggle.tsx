import { useState } from 'react';
import { Moon, Sun } from 'lucide-react';

function initial() {
  try {
    return (
      localStorage.getItem('agileplanner.theme') ||
      (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    );
  } catch {
    return 'light';
  }
}
const startingTheme = initial();
document.documentElement.dataset.theme = startingTheme;

export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || startingTheme);
  return (
    <button
      type="button"
      className="button secondary theme-toggle"
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      onClick={() => {
        const next = theme === 'dark' ? 'light' : 'dark';
        setTheme(next);
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem('agileplanner.theme', next);
        } catch {
          /* Theme remains usable without storage. */
        }
      }}>
      {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
      <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
    </button>
  );
}
