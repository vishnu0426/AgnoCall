import React, { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import { Alert, Button, Empty, Modal, Progress, Select, Space, Spin, Table, Tag, Tooltip, Typography } from 'antd';
import { CheckCircle2, FlaskConical, TriangleAlert } from 'lucide-react';
import { GET_CALLS_FOR_FORM_TEST } from '../../graphql/queries.js';
import { TEST_AI_FORM_EVALUATION } from '../../graphql/mutations.js';
import { formatWhen } from '../FormsLibrary/FormCard.jsx';

const { Text } = Typography;

const STATUS = {
    answered: { color: 'green', label: 'Answered' },
    not_applicable: { color: 'default', label: 'Not applicable' },
    missing: { color: 'orange', label: 'No answer' },
    invalid: { color: 'red', label: 'Invalid answer' },
};

const mmss = (sec) => (sec == null ? '' : `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`);

/**
 * Dry run: the AI answers THIS form (with your unsaved edits) for a real call, and you see what it would
 * record: each answer, the quote it relied on, and the score. Nothing is saved. It costs one AI request.
 */
const TryOnCallModal = ({ open, onClose, getContent, title, questionCount }) => {
    const { data, loading: loadingCalls, error: callsError } = useQuery(GET_CALLS_FOR_FORM_TEST, {
        skip: !open,
        fetchPolicy: 'network-only',
    });
    const [run, { data: result, loading: running, error: runError, reset }] = useMutation(TEST_AI_FORM_EVALUATION);
    const [callId, setCallId] = useState(null);

    const calls = data?.getCallsForFormTest || [];
    useEffect(() => {
        if (open && !callId && calls.length > 0) setCallId(calls[0].id);
    }, [open, calls.length]); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => { if (!open) reset(); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

    const out = result?.testAIFormEvaluation;

    const columns = [
        { title: 'Question', dataIndex: 'label', width: '28%', render: (t) => <Text strong style={{ fontSize: 13 }}>{t}</Text> },
        {
            title: 'AI answer',
            dataIndex: 'value',
            width: '16%',
            render: (v, row) => (
                row.status === 'answered'
                    ? <Text>{v}</Text>
                    : <Tag color={STATUS[row.status]?.color}>{STATUS[row.status]?.label || row.status}</Tag>
            ),
        },
        {
            title: 'What it relied on',
            dataIndex: 'evidence',
            render: (e, row) => {
                const reason = row.status === 'answered' ? null : row.reason;
                if (!e && !reason) return <Text type="secondary">None given</Text>;
                return (
                    <div style={{ fontSize: 12.5 }}>
                        {e && (
                            <>
                                <Text italic>&ldquo;{e}&rdquo;</Text>
                                {row.timestamp != null && <Text type="secondary"> at {mmss(row.timestamp)}</Text>}
                                {row.status === 'answered' && row.evidence_verified === false && (
                                    <Tooltip title="This quote was not found in the transcript, so the answer may be made up. In real runs it is flagged the same way.">
                                        <Tag color="red" icon={<TriangleAlert size={11} style={{ marginRight: 3 }} />} style={{ marginInlineStart: 6 }}>Quote not found</Tag>
                                    </Tooltip>
                                )}
                            </>
                        )}
                        {reason && <Text type="secondary" style={{ display: 'block' }}>{reason}</Text>}
                    </div>
                );
            },
        },
        {
            title: 'Confidence',
            dataIndex: 'confidence',
            width: 96,
            render: (c) => (c == null ? <Text type="secondary">-</Text> : <Text>{Math.round(c * 100)}%</Text>),
        },
    ];

    return (
        <Modal
            open={open}
            onCancel={onClose}
            width={920}
            title={<Space><FlaskConical size={18} /> Try this form on a real call</Space>}
            footer={<Button onClick={onClose}>Close</Button>}
        >
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                The AI answers the {questionCount} question{questionCount === 1 ? '' : 's'} as they are written now (including edits you
                have not saved) for the call you pick. <b>Nothing is saved.</b> It uses one AI request. Use it to check the wording
                before you publish or turn AI evaluation on.
            </Text>

            {callsError && <Alert type="error" showIcon message="Could not load calls" description={callsError.message} style={{ marginBottom: 12 }} />}
            {loadingCalls && !data ? (
                <div style={{ textAlign: 'center', padding: 16 }}><Spin /></div>
            ) : calls.length === 0 && !callsError ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No processed call with a transcript yet. Process a call first, then try again." />
            ) : (
                <Space wrap style={{ marginBottom: 16 }}>
                    <Select
                        showSearch
                        style={{ width: 460 }}
                        value={callId}
                        onChange={(v) => { setCallId(v); reset(); }}
                        optionFilterProp="label"
                        placeholder="Pick a call"
                        options={calls.map((c) => ({
                            value: c.id,
                            label: `${c.filename.length > 44 ? `${c.filename.slice(0, 44)}...` : c.filename}${c.call_date ? ` · ${formatWhen(c.call_date)}` : ''}${c.duration_seconds ? ` · ${mmss(c.duration_seconds)}` : ''}`,
                        }))}
                    />
                    <Button
                        type="primary"
                        icon={<FlaskConical size={15} />}
                        loading={running}
                        disabled={!callId || questionCount === 0}
                        onClick={() => run({ variables: { call_id: callId, form_content: getContent(), title } })}
                    >
                        {out ? 'Run again' : 'Run the test'}
                    </Button>
                    {running && <Text type="secondary">The AI is reading the call. This can take 10 to 30 seconds.</Text>}
                </Space>
            )}

            {runError && <Alert type="error" showIcon message="The test could not run" description={runError.message} style={{ marginBottom: 12 }} />}

            {out && (
                <>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, alignItems: 'center', marginBottom: 12 }}>
                        <div>
                            <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>Score the AI would give</Text>
                            <Text strong style={{ fontSize: 22 }}>{out.score == null ? 'n/a' : `${Math.round(out.score * 10) / 10}`}</Text>
                            {out.score != null && <Text type="secondary"> / {out.total_score}</Text>}
                        </div>
                        <div style={{ minWidth: 200 }}>
                            <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>Answered {out.answered} of {out.questions}</Text>
                            <Progress percent={Math.round(out.coverage * 100)} size="small" showInfo={false} status={out.coverage < 0.6 ? 'exception' : 'normal'} />
                        </div>
                        <Text type="secondary" style={{ fontSize: 12 }}>Model: {out.model}</Text>
                    </div>
                    {out.unverified_evidence > 0 && (
                        <Alert
                            type="warning"
                            showIcon
                            style={{ marginBottom: 12 }}
                            message={`${out.unverified_evidence} answer${out.unverified_evidence === 1 ? '' : 's'} quote${out.unverified_evidence === 1 ? 's' : ''} something not in the call`}
                            description="The AI cited words that do not appear in the transcript. Make that question more specific, or add an AI instruction saying what to look for."
                        />
                    )}
                    {out.coverage < 0.6 && (
                        <Alert
                            type="info"
                            showIcon
                            style={{ marginBottom: 12 }}
                            message="The AI could not answer many questions for this call"
                            description="Questions it cannot judge from a transcript (for example, anything about what was on screen) will be left out of the score. Consider rewording them or removing them."
                        />
                    )}
                    <Table
                        size="small"
                        rowKey="question_id"
                        columns={columns}
                        dataSource={out.answers}
                        pagination={false}
                        scroll={{ y: 360 }}
                    />
                    <Text type="secondary" style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 10, fontSize: 12.5 }}>
                        <CheckCircle2 size={13} /> Nothing was saved. This is a preview only.
                    </Text>
                </>
            )}
        </Modal>
    );
};

export default TryOnCallModal;
