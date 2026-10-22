import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
type Row = Record<string, any>;
const score = (v: any) => (typeof v === 'number' ? `${(v * 100).toFixed(1)}%` : 'Not scored');
const count = (v: any) => (typeof v === 'number' ? v.toLocaleString() : '—');
export function NgramMetrics({ values }: { values?: Row }) {
  if (!values) return <p>Reference-overlap metrics are unavailable for this response.</p>;
  return (
    <div className="ops-table">
      <table>
        <thead>
          <tr>
            <th>Order</th>
            <th>BLEU (cumulative)</th>
            <th>ROUGE precision</th>
            <th>ROUGE recall</th>
            <th>ROUGE F1</th>
          </tr>
        </thead>
        <tbody>
          {[2, 3, 4, 5].map((n) => (
            <tr key={n}>
              <td>{n}-gram</td>
              <td>{score(values.bleu?.[n])}</td>
              <td>{score(values.rouge?.[n]?.precision)}</td>
              <td>{score(values.rouge?.[n]?.recall)}</td>
              <td>{score(values.rouge?.[n]?.f1)}</td>
            </tr>
          ))}
          <tr>
            <td>ROUGE-L</td>
            <td>—</td>
            <td>{score(values.rouge_l?.precision)}</td>
            <td>{score(values.rouge_l?.recall)}</td>
            <td>{score(values.rouge_l?.f1)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
export function AggregateOverlap({ runs }: { runs: Row[] }) {
  return (
    <section className="ops-card">
      <h2>Reference overlap profile</h2>
      <p>
        BLEU measures matching phrases; ROUGE adds precision and coverage of expected wording. Evidence
        support, retrieval relevance and human ratings provide separate signals. These means cover completed,
        applicable answers—not failed requests.
      </p>
      <div className="ops-table">
        <table>
          <thead>
            <tr>
              <th>Model / run</th>
              {[2, 3, 4, 5].map((n) => (
                <th key={'b' + n}>BLEU-{n}</th>
              ))}
              {[2, 3, 4, 5].map((n) => (
                <th key={'r' + n}>ROUGE-{n} F1</th>
              ))}
              <th>ROUGE-L F1</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td>{run.model}</td>
                {[2, 3, 4, 5].map((n) => (
                  <td key={'b' + n}>{score(run.summary?.bleu?.[n])}</td>
                ))}
                {[2, 3, 4, 5].map((n) => (
                  <td key={'r' + n}>{score(run.summary?.rouge?.[n])}</td>
                ))}
                <td>{score(run.summary?.rouge_l)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Smoothed sentence BLEU with uniform cumulative weights; case-folded word tokens and no stemming. Texts
        shorter than an n-gram order are not applicable. Overlap alone does not establish factual correctness.
      </p>
    </section>
  );
}
export function QuestionComparison({ first, second }: { first: Row; second: Row }) {
  const items = new Map<string, { question: string; number: number; answers: (Row | undefined)[] }>();
  [first, second].forEach((run, index) =>
    run.results?.forEach((r: Row) => {
      const key = r.case_id || String(r.case_number);
      const entry = items.get(key) || { question: r.question, number: r.case_number, answers: [] };
      entry.answers[index] = r;
      items.set(key, entry);
    })
  );
  return (
    <section className="ops-card" aria-label="Per-question model comparison">
      <h2>Compare each question</h2>
      <p>
        Open a question to inspect both answers and all overlap scores. Latency covers answer generation;
        model/tool calls include the investigation for that question.
      </p>
      <div className="golden-case-list">
        {[...items.values()].map((entry, i) => (
          <details className="golden-case" key={i}>
            <summary>
              {entry.number}. {entry.question}
            </summary>
            <div className="ops-table">
              <table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Status</th>
                    <th>Answer latency</th>
                    <th>Model calls</th>
                    <th>Tool calls</th>
                    <th>Faithfulness</th>
                    <th>Context precision</th>
                    <th>BLEU-4</th>
                    <th>ROUGE-L F1</th>
                    <th>Human</th>
                  </tr>
                </thead>
                <tbody>
                  {[first, second].map((run, index) => {
                    const r = entry.answers[index];
                    return (
                      <tr key={run.id}>
                        <td>{run.model}</td>
                        <td>{r?.status || 'Not tested'}</td>
                        <td>
                          {typeof r?.generation_latency_ms === 'number'
                            ? `${(r.generation_latency_ms / 1000).toFixed(2)}s`
                            : '—'}
                        </td>
                        <td>{count(r?.model_calls)}</td>
                        <td>{count(r?.tool_calls)}</td>
                        <td>{score(r?.ragas?.metrics?.faithfulness)}</td>
                        <td>{score(r?.ragas?.metrics?.context_precision)}</td>
                        <td>{score(r?.metrics?.ngrams?.bleu?.['4'])}</td>
                        <td>{score(r?.metrics?.ngrams?.rouge_l?.f1)}</td>
                        <td>{r?.human?.score ? `${r.human.score}/5` : 'Awaiting review'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {entry.answers[0] &&
              entry.answers[1] &&
              (entry.answers[0].question !== entry.answers[1].question ||
                entry.answers[0].reference !== entry.answers[1].reference ||
                entry.answers[0].reference_status !== entry.answers[1].reference_status) && (
                <p className="ops-note">
                  The question, expected answer or reference verification changed between these runs. Their
                  reference scores use different expectations.
                </p>
              )}
            <div className="ops-answer-comparison">
              {[first, second].map((run, index) => {
                const r = entry.answers[index];
                return (
                  <article key={run.id}>
                    <h3>{run.model}</h3>
                    {r ? (
                      <>
                        <p className="muted">Expected answer: {r.reference_status?.replaceAll('_', ' ')}</p>
                        <details>
                          <summary>Expected answer used in this run</summary>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.reference || ''}</ReactMarkdown>
                        </details>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {r.response || r.error || 'No answer recorded.'}
                        </ReactMarkdown>
                        <NgramMetrics values={r.metrics?.ngrams} />
                        <ContextEvidence result={r} />
                        {r.metric_story?.map((text: string, n: number) => (
                          <p className="ops-note" key={n}>
                            {text}
                          </p>
                        ))}
                      </>
                    ) : (
                      <p>This run has no answer for this question.</p>
                    )}
                  </article>
                );
              })}
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}

export function ContextEvidence({ result }: { result: Row }) {
  return (
    <details className="ops-card">
      <summary>Expected evidence & actual retrieval</summary>
      <p>
        Expected evidence: {result.reference_contexts?.length || 0} chunks ·{' '}
        {result.context_status || 'missing'}. Actual retrieved evidence:{' '}
        {result.retrieved_contexts?.length || 0} chunks.
      </p>
      <p className="muted">{result.context_source}</p>
      <div className="ops-answer-comparison">
        <div>
          <h4>Expected / reference context</h4>
          {result.reference_contexts?.map((text: string, i: number) => (
            <pre key={i}>{text}</pre>
          ))}
          {!result.reference_contexts?.length && (
            <p>No expected context was recorded for this historical test.</p>
          )}
        </div>
        <div>
          <h4>Actually retrieved context</h4>
          {result.retrieved_contexts?.map((text: string, i: number) => (
            <pre key={i}>{text}</pre>
          ))}
          {!result.retrieved_contexts?.length && <p>No actual retrieval was recorded.</p>}
        </div>
      </div>
      <p>
        Reference-answer recall: {score(result.ragas?.metrics?.context_recall)} · Direct context text recall:{' '}
        {score(result.ragas?.metrics?.context_text_recall)} · Direct context text precision:{' '}
        {score(result.ragas?.metrics?.context_text_precision)}
      </p>
      <p className="muted">
        Context text matching is a wording/chunk-boundary heuristic. Ragas scoring may use a bounded evidence
        sample; inspect the recorded coverage in metric details.
      </p>
    </details>
  );
}
