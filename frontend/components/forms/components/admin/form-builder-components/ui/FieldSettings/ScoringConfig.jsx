import React from 'react';
import { InputNumber, Switch, Typography, Divider } from 'antd';

const { Text } = Typography;

const ScoringConfig = ({ field, onUpdate, formSettings }) => {
    const maxAllowed = formSettings.totalScore || 100;

    return (
        <div style={{ marginBottom: '20px' }}>
            <Text strong style={{ fontSize: '13px', display: 'block', marginBottom: '12px' }}>Scoring Configuration</Text>
            <div style={{
                background: '#fffbe6',
                border: '1px solid #ffe58f',
                borderRadius: '8px',
                padding: '12px',
            }}>
                <Text style={{ fontSize: '12px', display: 'block', marginBottom: '8px' }}>
                    Max Points for this field (out of {maxAllowed})
                </Text>
                <InputNumber
                    min={0}
                    max={maxAllowed}
                    value={field.max_score || 10}
                    onChange={(val) => onUpdate(field.id, { max_score: Math.min(val || 0, maxAllowed) })}
                    style={{ width: '100%' }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginTop: 14 }}>
                    <div>
                        <Text strong style={{ fontSize: '12px', display: 'block' }}>Critical question</Text>
                        <Text type="secondary" style={{ fontSize: '11.5px', display: 'block' }}>
                            If the answer earns 0 points, the whole form scores 0 (automatic fail).
                        </Text>
                    </div>
                    <Switch
                        size="small"
                        checked={!!field.critical}
                        onChange={(val) => onUpdate(field.id, { critical: val })}
                    />
                </div>
            </div>
            <Divider style={{ margin: '16px 0' }} />
        </div>
    );
};

export default ScoringConfig;
