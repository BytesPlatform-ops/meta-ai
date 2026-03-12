-- Co-Pilot V2+V3: Add advanced + agentic action types to proposal_action enum
-- Run this against the live DB if it already has the original enum

-- V2 actions
ALTER TYPE proposal_action ADD VALUE IF NOT EXISTS 'refresh_creative';
ALTER TYPE proposal_action ADD VALUE IF NOT EXISTS 'prune_placements';
ALTER TYPE proposal_action ADD VALUE IF NOT EXISTS 'consolidate_adsets';
ALTER TYPE proposal_action ADD VALUE IF NOT EXISTS 'apply_cost_cap';

-- V3 agentic actions
ALTER TYPE proposal_action ADD VALUE IF NOT EXISTS 'mutate_winner';
ALTER TYPE proposal_action ADD VALUE IF NOT EXISTS 'shift_budget';
ALTER TYPE proposal_action ADD VALUE IF NOT EXISTS 'create_lookalike';
