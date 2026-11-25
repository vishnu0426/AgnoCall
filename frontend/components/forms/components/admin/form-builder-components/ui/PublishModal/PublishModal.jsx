import React from 'react';
import { Alert, Button, Modal, Typography } from 'antd';
import { AlertTriangle, XCircle } from 'lucide-react';

const { Text } = Typography;

/**
 * The last stop before a form goes live. Errors block (the form would be broken); warnings are shown
 * and can be published anyway. When AI is scoring calls with this form, say plainly that publishing
 * changes it for every new call immediately.
 */
const PublishModal = ({ open, issues = [], aiLive, busy, onConfirm, onClose, onFocusField }) => {
    const errors = issues.filter((i) => i.level === 'error');
    const warnings = issues.filter((i) => i.level === 'warning');
    const blocked = errors.length > 0;

    const row = (issue, i, Icon, color) => (
        <li key={`${issue.level}-${i}`} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 0' }}>
            <Icon size={15} style={{ color, marginTop: 3, flexShrink: 0 }} />
            <span style={{ fontSize: 13.5 }}>
                {issue.text}
                {issue.fieldId && onFocusField && (
                    <Button type="link" size="small" onClick={() => onFocusField(issue.fieldId)}>Go to question</Button>
                )}
            </span>
        </li>
    );

    return (
        <Modal
            open={open}
            onCancel={onClose}
            title={blocked ? 'Fix these before publishing' : 'Publish this form?'}
            width={560}
            footer={[
                <Button key="cancel" onClick={onClose}>{blocked ? 'Close' : 'Keep editing'}</Button>,
                !blocked && (
                    <Button key="go" type="primary" loading={busy} onClick={onConfirm}>
                        {warnings.length ? 'Publish anyway' : 'Publish'}
                    </Button>
                ),
            ]}
        >
            {!blocked && (
                <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                    Publishing makes these edits the live version. Until you publish, reviewers and the AI keep using the current one.
                </Text>
            )}
            {aiLive && !blocked && (
                <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 12 }}
                    message="AI scoring uses this form"
                    description="From the moment you publish, every newly processed call is scored with the new version. Calls already scored keep their old score and the version they were scored with."
                />
            )}
            {errors.length > 0 && (
                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                    {errors.map((e, i) => row(e, i, XCircle, '#C1352E'))}
                </ul>
            )}
            {warnings.length > 0 && (
                <>
                    {errors.length > 0 && <Text type="secondary" style={{ display: 'block', margin: '12px 0 4px' }}>Also worth a look:</Text>}
                    <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                        {warnings.map((w, i) => row(w, i, AlertTriangle, '#B7791F'))}
                    </ul>
                </>
            )}
        </Modal>
    );
};

export default PublishModal;
