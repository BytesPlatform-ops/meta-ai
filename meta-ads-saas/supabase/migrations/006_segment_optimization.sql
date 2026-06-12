-- Add segment optimization action types
ALTER TYPE proposal_action ADD VALUE IF NOT EXISTS 'exclude_demographics';
ALTER TYPE proposal_action ADD VALUE IF NOT EXISTS 'update_placements';
