import { useEffect, useState } from 'react';
import { api } from './api';

type Option = {
  id: string;
  label: string;
  model: string;
  chunk_characters: number;
  chunk_overlap: number;
  download: string;
};

export default function EmbeddingChoice({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const [options, setOptions] = useState<Option[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    api<{ options: Option[] }>('/agent/embedding-options')
      .then((data) => {
        if (live) setOptions(data.options);
      })
      .catch(() => {
        if (live) setError('Embedding choices could not be loaded. Refresh to retry.');
      });
    return () => {
      live = false;
    };
  }, []);
  const chosen = options.find((option) => option.id === value);
  return (
    <div className="embedding-choice">
      <label>
        Embedding model &amp; chunk size
        <select
          aria-label="Embedding model and chunk size"
          value={value}
          disabled={disabled || !options.length}
          onChange={(e) => onChange(e.target.value)}>
          {value === '' && <option value="">Current server configuration</option>}
          <option value="lexical">Keyword search only · no model needed</option>
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label} · {option.chunk_characters.toLocaleString()} characters
            </option>
          ))}
        </select>
      </label>
      <p className="small muted">
        Want larger chunks? Choose the larger local model. Both embedding models run on your device with no
        API fees.
      </p>
      {chosen && (
        <p className="small muted">
          Maximum {chosen.chunk_characters.toLocaleString()} characters per chunk, including the title ·{' '}
          {chosen.chunk_overlap} characters of narrative overlap.{' '}
          {value === 'large'
            ? 'Larger model uses more memory and may take longer.'
            : 'Smaller model uses less memory; shorter chunks can create more vectors.'}{' '}
          Install once: <code>ollama pull {chosen.model}</code> ({chosen.download} download).
        </p>
      )}
      {value === 'lexical' && (
        <p className="small muted">
          Local keyword and lexical vector search. Choose either embedding model to enable semantic search.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
