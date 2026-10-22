"""Reference wording overlap, kept separate from evidence support and factual correctness."""

import hashlib
import re
from functools import lru_cache


class Tokenizer:
    def tokenize(self, text):
        return re.findall(r'\w+', text.casefold(), flags=re.UNICODE)


@lru_cache(maxsize=1)
def scorer():
    from rouge_score.rouge_scorer import RougeScorer

    return RougeScorer(['rouge2', 'rouge3', 'rouge4', 'rouge5', 'rougeL'], tokenizer=Tokenizer())


def overlap(reference, answer):
    from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu

    tokenizer = Tokenizer()
    ref, hyp = tokenizer.tokenize(reference), tokenizer.tokenize(answer)
    scores = scorer().score(reference, answer)
    bleu, rouge = {}, {}
    for n in range(2, 6):
        applicable = min(len(ref), len(hyp)) >= n
        bleu[str(n)] = (
            float(
                sentence_bleu(
                    [ref], hyp, weights=(1 / n,) * n, smoothing_function=SmoothingFunction().method1
                )
            )
            if applicable
            else None
        )
        value = scores['rouge' + str(n)]
        rouge[str(n)] = (
            {'precision': value.precision, 'recall': value.recall, 'f1': value.fmeasure}
            if applicable
            else None
        )
    value = scores['rougeL']
    return {
        'version': 1,
        'source_hash': hashlib.sha256((reference + '\0' + answer).encode()).hexdigest(),
        'bleu': bleu,
        'rouge': rouge,
        'rouge_l': {'precision': value.precision, 'recall': value.recall, 'f1': value.fmeasure},
        'reference_tokens': len(ref),
        'answer_tokens': len(hyp),
        'method': 'Sentence BLEU-N: uniform cumulative weights, Chen-Cherry method 1 smoothing. ROUGE-N: multiset precision/recall/F1. ROUGE-L: longest common subsequence. Shared Unicode word tokens, case-folded, no stemming. Orders longer than either text are not applicable.',
        'note': 'Reference wording overlap is not factual correctness. Paraphrases may score low; copying incorrect references may score high.',
    }


def ensure_metrics(result):
    if result.get('reference_validation'):
        return None
    if result.get('status') != 'success' or not result.get('reference') or not result.get('response'):
        return None
    expected = hashlib.sha256((result['reference'] + '\0' + result['response']).encode()).hexdigest()
    value = result.get('metrics', {}).get('ngrams')
    if not value or value.get('source_hash') != expected:
        value = overlap(result['reference'], result['response'])
        from .. import store

        store.mongo().agent_eval_results.update_one({'id': result['id']}, {'$set': {'metrics.ngrams': value}})
    result.setdefault('metrics', {})['ngrams'] = value
    return value


def narrative(metrics, ragas, verified=False):
    values = []
    if not verified:
        values.append('The expected answer is not verified. Treat reference-overlap scores as provisional.')
    faith = (ragas or {}).get('metrics', {}).get('faithfulness')
    bleu = (metrics or {}).get('bleu', {}).get('4')
    coverage = (metrics or {}).get('rouge_l', {}).get('f1')
    if isinstance(faith, (int, float)) and faith < 0.5:
        values.append(
            'Evidence support is low in the judged packet. Check unsupported claims before trusting wording overlap.'
        )
    elif isinstance(faith, (int, float)) and faith >= 0.8 and coverage is not None and coverage < 0.4:
        values.append(
            'Evidence support is strong but wording overlap is low. This may be a valid paraphrase; human review can distinguish it from missing detail.'
        )
    if bleu is not None and coverage is not None:
        if bleu < 0.2 and coverage >= 0.5:
            values.append(
                'Reference content overlaps more than exact phrases: sentence structure or phrasing differs.'
            )
        elif bleu >= 0.6 and coverage >= 0.6:
            values.append(
                'The answer closely follows the expected wording. Verify the evidence and reference correctness as separate checks.'
            )
        else:
            values.append(
                'Use BLEU for phrase precision and ROUGE for expected-content overlap, alongside evidence support and human ratings.'
            )
    return values
