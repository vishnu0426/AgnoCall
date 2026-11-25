import React from 'react';
import { Typography, theme as antdTheme } from 'antd';

const { Text } = Typography;

/** A compact tile: icon + name. The longer description is the hover text. */
const PaletteItem = ({ fieldType, onDragStart, onAdd }) => {
    const { token } = antdTheme.useToken();
    const Icon = fieldType.icon;

    return (
        <div
            className="palette-item"
            draggable
            title={`${fieldType.description}. Click to add, or drag onto the form.`}
            onDragStart={(e) => {
                e.dataTransfer.effectAllowed = 'copy';
                e.dataTransfer.setData('text/plain', fieldType.type);
                onDragStart(fieldType.type);
            }}
            onClick={() => onAdd && onAdd(fieldType.type)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onAdd && onAdd(fieldType.type); } }}
            role="button"
            tabIndex={0}
            style={{
                cursor: 'pointer',
                background: token.colorBgContainer,
                border: `1px solid ${token.colorBorderSecondary}`,
                borderRadius: 8,
                transition: 'all 0.15s ease',
                padding: '8px 10px',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                minWidth: 0,
            }}
        >
            <Icon size={15} style={{ color: token.colorPrimary, flexShrink: 0 }} />
            <Text style={{ fontSize: 12.5 }} ellipsis>{fieldType.label}</Text>
        </div>
    );
};

export default PaletteItem;
