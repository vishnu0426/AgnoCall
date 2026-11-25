import React from 'react';
import { Button, Popconfirm, Tag, Tooltip, Typography, theme as antdTheme } from 'antd';
import { Copy, Sparkles, Trash2 } from 'lucide-react';

const { Text } = Typography;

// The API sends ISO-8601 strings. (This used to parseInt() them, which turned "2026-11-25T..." into
// the number 2026 and displayed 1/1/1970.)
export const formatWhen = (value) => {
    if (!value) return '';
    const n = /^\d{10,}$/.test(String(value)) ? Number(value) : Date.parse(value);
    const d = new Date(n);
    return Number.isNaN(d.getTime())
        ? ''
        : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
};

const countQuestions = (form) => {
    try {
        return (JSON.parse(form.form_content).fields || []).length;
    } catch {
        return 0;
    }
};

const FormCard = ({ form, isSelected, onSelect, onDelete, onDuplicate }) => {
    const { token } = antdTheme.useToken();
    const when = formatWhen(form.updatedAt || form.createdAt);
    const n = countQuestions(form);
    return (
        <div
            role="button"
            tabIndex={0}
            className={`form-item-card ${isSelected ? 'active' : ''}`}
            onClick={() => onSelect(form)}
            onKeyDown={(e) => { if (e.key === 'Enter') onSelect(form); }}
            style={{
                marginBottom: 8,
                padding: '10px 12px',
                borderRadius: 8,
                cursor: 'pointer',
                border: `1px solid ${isSelected ? token.colorPrimary : token.colorBorderSecondary}`,
                background: isSelected ? token.colorPrimaryBg : token.colorBgContainer,
                transition: 'border-color 0.15s ease, background 0.15s ease',
            }}
        >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <Text strong style={{ display: 'block', fontSize: 13.5 }} ellipsis={{ tooltip: form.title }}>{form.title}</Text>
                    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 4, marginTop: 4 }}>
                        <Tag style={{ marginInlineEnd: 0 }}>v{form.version || 1}</Tag>
                        <Tag style={{ marginInlineEnd: 0 }}>{n} question{n === 1 ? '' : 's'}</Tag>
                        {form.has_draft && <Tag color="gold" style={{ marginInlineEnd: 0 }}>Draft</Tag>}
                        {form.ai_enabled && (
                            <Tag color="blue" icon={<Sparkles size={10} style={{ marginRight: 3 }} />} style={{ marginInlineEnd: 0 }}>
                                AI
                            </Tag>
                        )}
                    </div>
                    {when && <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>Updated {when}</Text>}
                </div>
                <div style={{ display: 'flex', flexShrink: 0 }}>
                <Tooltip title="Make a copy (AI evaluation starts off)">
                    <Button
                        type="text"
                        size="small"
                        aria-label={`Copy ${form.title}`}
                        onClick={(e) => { e.stopPropagation(); onDuplicate && onDuplicate(form); }}
                        icon={<Copy size={14} />}
                    />
                </Tooltip>
                <Popconfirm
                    title="Delete this form?"
                    description={form.ai_enabled ? 'AI scoring will stop for this form. This cannot be undone.' : 'This cannot be undone.'}
                    onConfirm={(e) => { e?.stopPropagation(); onDelete(form.id); }}
                    onCancel={(e) => e?.stopPropagation()}
                    okText="Delete"
                    cancelText="Cancel"
                    okButtonProps={{ danger: true }}
                >
                    <Button type="text" size="small" danger onClick={(e) => e.stopPropagation()} aria-label={`Delete ${form.title}`} icon={<Trash2 size={14} />} />
                </Popconfirm>
                </div>
            </div>
        </div>
    );
};

export default FormCard;
