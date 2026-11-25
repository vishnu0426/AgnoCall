import React, { useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import { Button, Space, Switch, InputNumber, Input, Tooltip, Typography, Select, Modal, Form, Tag, Popconfirm, theme as antdTheme } from 'antd';
import { Save, Eye, Palette, Edit3, Languages, Sparkles, History, Rocket, Undo2, Clock, FlaskConical } from 'lucide-react';
import { GET_AI_EVALUATION_LIMITS } from '../../graphql/queries.js';
import { BACKFILL_AI_FORM_EVALUATION } from '../../graphql/mutations.js';
import { DEFAULT_LANGUAGE, languageOptions, getLanguage } from '../../constants/languages.js';

const { Text } = Typography;

const BuilderHeader = ({
    form, formFields, formSettings, setFormSettings, onTotalScoreChange,
    onRename, onPreview, onThemeSettings, translating = false,
    status = 'published', dirty = false, onSaveDraft, onPublish, onDiscard, onHistory, onTryAI, publishing = false
}) => {
    const { token } = antdTheme.useToken();
    const { data: limitsData } = useQuery(GET_AI_EVALUATION_LIMITS, { fetchPolicy: 'cache-and-network' });
    const limits = limitsData?.getAIEvaluationLimits;
    // The saved flag counts toward the cap, so this form's own toggle never blocks itself.
    const atLimit = !!limits && limits.enabled_count >= limits.max_enabled_forms && !form?.ai_enabled;
    const aiUnavailable = limits && !limits.feature_enabled;

    // Backfill: score past calls with this form. Always previews first (dry
    // run) so the admin sees how many LLM requests they are about to spend.
    const [backfillOpen, setBackfillOpen] = useState(false);
    const [range, setRange] = useState({ from: '', to: '' });
    const [preview, setPreview] = useState(null);
    const [backfillError, setBackfillError] = useState(null);
    const [backfill, { loading: backfilling }] = useMutation(BACKFILL_AI_FORM_EVALUATION);
    const runBackfill = async (dryRun) => {
        setBackfillError(null);
        try {
            const res = await backfill({
                variables: {
                    form_id: form.form_id,
                    date_from: range.from || null,
                    date_to: range.to || null,
                    dry_run: dryRun,
                },
            });
            const out = res?.data?.backfillAIFormEvaluation;
            setPreview(out);
            if (!dryRun) setBackfillOpen(false);
        } catch (err) {
            setPreview(null);
            setBackfillError(err?.message || 'Backfill failed');
        }
    };
    const [isEditing, setIsEditing] = useState(false);
    const [editTitle, setEditTitle] = useState('');
    const [langModal, setLangModal] = useState(false);
    const [langDraft, setLangDraft] = useState({ languages: [], defaultLanguage: DEFAULT_LANGUAGE });

    const handleTitleSave = () => {
        if (editTitle.trim()) {
            onRename(editTitle.trim());
        }
        setIsEditing(false);
    };

    const openLangModal = () => {
        setLangDraft({
            languages: formSettings.languages?.length ? formSettings.languages : [DEFAULT_LANGUAGE],
            defaultLanguage: formSettings.defaultLanguage || DEFAULT_LANGUAGE,
        });
        setLangModal(true);
    };

    const confirmLanguages = () => {
        if (!langDraft.languages.length) {
            return; // Select is required to hold at least one language
        }
        setFormSettings(prev => ({
            ...prev,
            languages: langDraft.languages,
            defaultLanguage: langDraft.languages.includes(langDraft.defaultLanguage)
                ? langDraft.defaultLanguage
                : langDraft.languages[0],
        }));
        setLangModal(false);
    };

    if (!form) return null;

    const languages = formSettings.languages?.length ? formSettings.languages : [DEFAULT_LANGUAGE];

    const label = { fontSize: 13, whiteSpace: 'nowrap' };

    return (
        <div className="builder-header" style={{ background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
            {/* Row 1: which form, and the things you do with it */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, padding: '12px 24px', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0, flex: '1 1 260px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                    {isEditing ? (
                        <Input
                            autoFocus
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            onPressEnter={handleTitleSave}
                            onBlur={handleTitleSave}
                            style={{ maxWidth: 320 }}
                        />
                    ) : (
                        <>
                            <Text strong style={{ fontSize: 18, minWidth: 0 }} ellipsis={{ tooltip: form.title }}>{form.title}</Text>
                            <Tooltip title="Rename">
                                <Button
                                    type="text"
                                    size="small"
                                    aria-label="Rename form"
                                    icon={<Edit3 size={14} />}
                                    onClick={() => { setEditTitle(form.title); setIsEditing(true); }}
                                />
                            </Tooltip>
                        </>
                    )}
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
                    <Tag style={{ marginInlineEnd: 0 }}>{formFields.length} question{formFields.length !== 1 ? 's' : ''}</Tag>
                    <Tag style={{ marginInlineEnd: 0 }}>v{form.version || 1}</Tag>
                    {form?.ai_enabled && formSettings.aiEnabled && (
                        <Tag color="blue" icon={<Sparkles size={11} style={{ marginRight: 4 }} />} style={{ marginInlineEnd: 0 }}>
                            AI scoring on
                        </Tag>
                    )}
                    {status === 'unsaved' && <Tag color="orange" style={{ marginInlineEnd: 0 }}>Unsaved changes</Tag>}
                    {status === 'draft' && (
                        <Tooltip title="Saved as a draft. Reviewers and the AI still use the published version until you publish.">
                            <Tag color="gold" style={{ marginInlineEnd: 0 }}>Draft saved, not live</Tag>
                        </Tooltip>
                    )}
                    {status === 'published' && <Tag color="green" style={{ marginInlineEnd: 0 }}>Published</Tag>}
                    </div>
                </div>
                <Space wrap>
                    {form?.ai_enabled && formSettings.aiEnabled && (
                        <Tooltip title="Score past calls with this form">
                            <Button
                                icon={<History size={16} />}
                                onClick={() => { setPreview(null); setBackfillError(null); setBackfillOpen(true); }}
                            >
                                Backfill
                            </Button>
                        </Tooltip>
                    )}
                    <Tooltip title="Earlier published versions">
                        <Button icon={<Clock size={16} />} onClick={onHistory}>History</Button>
                    </Tooltip>
                    <Tooltip title="Colours and background of the form">
                        <Button icon={<Palette size={16} />} onClick={onThemeSettings}>Theme</Button>
                    </Tooltip>
                    <Tooltip title="See the form as a person filling it in">
                        <Button icon={<Eye size={16} />} onClick={onPreview}>Preview</Button>
                    </Tooltip>
                    {(dirty || form?.has_draft) && (
                        <Popconfirm
                            title={form?.has_draft ? 'Discard the draft?' : 'Revert your changes?'}
                            description={form?.has_draft
                                ? 'The editor goes back to the published version. Your draft is deleted.'
                                : 'Your edits since the last save are lost.'}
                            okText={form?.has_draft ? 'Discard draft' : 'Revert'}
                            okButtonProps={{ danger: true }}
                            onConfirm={onDiscard}
                        >
                            <Button icon={<Undo2 size={16} />}>{form?.has_draft ? 'Discard draft' : 'Revert'}</Button>
                        </Popconfirm>
                    )}
                    <Tooltip title="Keep these edits without making them live">
                        <Button icon={<Save size={16} />} onClick={onSaveDraft} disabled={!dirty} loading={translating}>
                            Save draft
                        </Button>
                    </Tooltip>
                    <Tooltip title={dirty || form?.has_draft ? 'Make these edits the live version' : 'Nothing to publish: no changes since the last publish'}>
                        <Button
                            type="primary"
                            icon={<Rocket size={16} />}
                            onClick={onPublish}
                            disabled={!dirty && !form?.has_draft}
                            loading={publishing}
                        >
                            Publish
                        </Button>
                    </Tooltip>
                </Space>
            </div>

            {/* Row 2: how this form behaves */}
            <div style={{
                display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '8px 28px', padding: '8px 24px',
                background: token.colorFillQuaternary, borderTop: `1px solid ${token.colorBorderSecondary}`,
            }}>
                <Tooltip title="Languages this form is offered in">
                    <Button size="small" type="text" icon={<Languages size={15} />} onClick={openLangModal}>
                        {languages.map((c) => getLanguage(c).native).join(' · ')}
                    </Button>
                </Tooltip>
                <Space size={8}>
                    <Text style={label}>Scoring</Text>
                    <Switch
                        size="small"
                        checked={formSettings.hasScoring}
                        onChange={(val) => setFormSettings(prev => ({ ...prev, hasScoring: val }))}
                    />
                    {formSettings.hasScoring && (
                        <>
                            <Text style={{ ...label, color: token.colorTextSecondary }}>Total points</Text>
                            <InputNumber
                                min={1}
                                max={10000}
                                value={formSettings.totalScore}
                                onChange={(val) => onTotalScoreChange ? onTotalScoreChange(val || 100) : setFormSettings(prev => ({ ...prev, totalScore: val || 100 }))}
                                style={{ width: 76 }}
                                size="small"
                            />
                        </>
                    )}
                </Space>
                <Tooltip
                    title={
                        aiUnavailable
                            ? 'AI evaluation is disabled on this deployment.'
                            : atLimit
                                ? `Limit reached: ${limits.enabled_count}/${limits.max_enabled_forms} forms already use AI evaluation. Disable another form first.`
                                : 'When on, the AI scores EVERY new call against this form. Each enabled form adds one LLM call per call processed. Applied when you save.'
                    }
                >
                    <Space size={8}>
                        <Sparkles size={14} />
                        <Text style={label}>AI evaluation</Text>
                        <Switch
                            size="small"
                            checked={!!formSettings.aiEnabled}
                            disabled={aiUnavailable || (atLimit && !formSettings.aiEnabled)}
                            onChange={(val) => setFormSettings(prev => ({ ...prev, aiEnabled: val }))}
                        />
                        {limits && (
                            <Tag color={atLimit ? 'orange' : 'default'} style={{ marginInlineEnd: 0 }}>
                                {limits.enabled_count} of {limits.max_enabled_forms} forms
                            </Tag>
                        )}
                    </Space>
                </Tooltip>
                <Tooltip title={formFields.length === 0
                    ? 'Add a question first'
                    : 'See what the AI would answer for a real call, using these questions as they are now. Nothing is saved.'}>
                    <Button size="small" icon={<FlaskConical size={14} />} onClick={onTryAI} disabled={formFields.length === 0}>
                        Try on a real call
                    </Button>
                </Tooltip>
            </div>

            <Modal
                title="Backfill AI evaluation"
                open={backfillOpen}
                onCancel={() => setBackfillOpen(false)}
                footer={[
                    <Button key="cancel" onClick={() => setBackfillOpen(false)}>Cancel</Button>,
                    <Button key="preview" loading={backfilling} onClick={() => runBackfill(true)}>
                        Preview
                    </Button>,
                    <Button
                        key="run"
                        type="primary"
                        loading={backfilling}
                        disabled={!preview || preview.eligible === 0}
                        onClick={() => runBackfill(false)}
                    >
                        {preview ? `Evaluate ${preview.eligible} call${preview.eligible === 1 ? '' : 's'}` : 'Evaluate'}
                    </Button>,
                ]}
            >
                <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                    Scores already-processed calls that have no AI evaluation of this form yet. Each call
                    costs one LLM request. Leave dates empty for all calls.
                </Text>
                <Space>
                    <Input type="date" value={range.from} onChange={(e) => { setRange(r => ({ ...r, from: e.target.value })); setPreview(null); }} />
                    <Text>to</Text>
                    <Input type="date" value={range.to} onChange={(e) => { setRange(r => ({ ...r, to: e.target.value })); setPreview(null); }} />
                </Space>
                {preview && (
                    <div style={{ marginTop: 12 }}>
                        <Text strong>{preview.eligible}</Text> call{preview.eligible === 1 ? '' : 's'} would be evaluated.
                        {preview.truncated && (
                            <Text type="warning" style={{ display: 'block' }}>
                                More calls match than the per-request limit ({preview.max_calls}). Run again afterwards to continue.
                            </Text>
                        )}
                    </div>
                )}
                {backfillError && <Text type="danger" style={{ display: 'block', marginTop: 12 }}>{backfillError}</Text>}
            </Modal>

            <Modal
                title="Form Languages"
                open={langModal}
                onOk={confirmLanguages}
                onCancel={() => setLangModal(false)}
                okText="Apply"
                cancelText="Cancel"
                width={520}
            >
                <Form layout="vertical">
                    <Form.Item
                        label="Languages"
                        extra="Pick every language the form is offered in — each shown in its own script. Adding a language opens a tab for it in every field editor."
                    >
                        <Select
                            mode="multiple"
                            showSearch
                            optionFilterProp="label"
                            placeholder="Select languages"
                            value={langDraft.languages}
                            onChange={(vals) => setLangDraft(prev => {
                                let defaultLang = prev.defaultLanguage;
                                if (!vals.includes(defaultLang)) defaultLang = vals[0] || DEFAULT_LANGUAGE;
                                return { ...prev, languages: vals, defaultLanguage: defaultLang };
                            })}
                            options={languageOptions()}
                            maxTagCount="responsive"
                            style={{ width: '100%' }}
                        />
                    </Form.Item>
                    <Form.Item
                        label="Default Language"
                        extra="The source language you write fields in. Save fills every other language automatically."
                    >
                        <Select
                            showSearch
                            optionFilterProp="label"
                            value={langDraft.defaultLanguage}
                            onChange={(val) => setLangDraft(prev => ({ ...prev, defaultLanguage: val }))}
                            options={languageOptions(langDraft.languages)}
                            style={{ width: '100%' }}
                        />
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default BuilderHeader;
