import { isScorableField } from './fieldDefaults.js';

const CHOICE_TYPES = new Set(['dropdown', 'radio', 'checkbox', 'segmented']);

/**
 * Problems a person should know about before a form goes live.
 * Returns [{ level: 'error' | 'warning', fieldId?, text }]. Errors block publishing (the form would be
 * broken or unscorable); warnings can be published anyway.
 */
export function validateForm(fields = [], settings = {}) {
    const issues = [];
    const name = (f, i) => (f.label && f.label.trim() ? `"${f.label.trim()}"` : `Question ${i + 1}`);

    if (fields.length === 0) {
        issues.push({ level: 'error', text: 'The form has no questions.' });
        return issues;
    }

    const seen = new Map();
    fields.forEach((f, i) => {
        if (!f.label || !f.label.trim()) {
            issues.push({ level: 'error', fieldId: f.id, text: `Question ${i + 1} has no label.` });
        } else {
            const key = f.label.trim().toLowerCase();
            if (seen.has(key)) {
                issues.push({ level: 'warning', fieldId: f.id, text: `${name(f, i)} appears more than once: people (and the AI) cannot tell the copies apart.` });
            }
            seen.set(key, true);
        }
        if (CHOICE_TYPES.has(f.type)) {
            const options = f.options || [];
            if (options.length < 2) {
                issues.push({ level: 'error', fieldId: f.id, text: `${name(f, i)} needs at least two answer options.` });
            } else if (options.some((o) => !o.label || !String(o.label).trim())) {
                issues.push({ level: 'error', fieldId: f.id, text: `${name(f, i)} has an answer option with no text.` });
            }
        }
    });

    // A section heading that groups nothing scored shows no score: usually a heading left empty.
    if (settings.hasScoring) {
        fields.forEach((f, i) => {
            if (f.type !== 'section') return;
            const next = fields.findIndex((g, j) => j > i && g.type === 'section');
            const below = fields.slice(i + 1, next === -1 ? undefined : next);
            if (!below.some((g) => isScorableField(g.type))) {
                issues.push({ level: 'warning', fieldId: f.id, text: `The section "${(f.label || '').trim() || 'Untitled'}" has no scored question under it, so it will show no score.` });
            }
        });
        fields.forEach((f, i) => {
            if (f.critical && isScorableField(f.type) && Number(f.max_score) <= 0) {
                issues.push({ level: 'warning', fieldId: f.id, text: `"${(f.label || '').trim() || `Question ${i + 1}`}" is critical but worth 0 points, so it can never fail the form.` });
            }
        });
    }
    if (!settings.hasScoring && fields.some((f) => f.critical)) {
        issues.push({ level: 'warning', text: 'Some questions are marked critical, but scoring is off, so they have no effect.' });
    }

    if (settings.hasScoring) {
        const scorable = fields.filter((f) => isScorableField(f.type));
        const total = Number(settings.totalScore) || 100;
        if (scorable.length === 0) {
            issues.push({ level: 'warning', text: 'Scoring is on, but no question can be scored.' });
        } else {
            const points = scorable.reduce((sum, f) => sum + (Number(f.max_score) || 0), 0);
            if (Math.round(points) !== Math.round(total)) {
                issues.push({ level: 'warning', text: `The question points add up to ${Math.round(points)}, not the total of ${total}.` });
            }
        }
    }

    if (settings.aiEnabled) {
        // Mirrors the server (tasks/form_eval.py extract_questions): scored fields are answered
        // automatically; text fields only when they carry an AI instruction.
        const instructed = (f) => ['text', 'textarea'].includes(f.type) && String(f.ai_instruction || '').trim();
        const answerable = fields.filter((f) => isScorableField(f.type) || instructed(f));
        if (answerable.length === 0) {
            issues.push({ level: 'error', text: 'AI evaluation is on, but there is no question the AI can answer. Add a scored question, or an AI instruction to a text question.' });
        }
        const skipped = fields.filter((f) => ['text', 'textarea'].includes(f.type) && !instructed(f));
        if (skipped.length > 0) {
            issues.push({ level: 'warning', text: `${skipped.length} text question${skipped.length === 1 ? '' : 's'} ha${skipped.length === 1 ? 's' : 've'} no AI instruction, so the AI will leave ${skipped.length === 1 ? 'it' : 'them'} blank.` });
        }
    }
    return issues;
}
