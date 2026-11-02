-- 002_triggers.sql: Integrity triggers for spatial overlap, status history, and order placement

-- 1. Overlap Check Trigger
-- DECISION 2: reject if ST_Intersects AND NOT ST_Touches against any other plot
CREATE OR REPLACE FUNCTION check_plot_overlap()
RETURNS TRIGGER AS $$
DECLARE
    conflicting_plot_id VARCHAR(64);
BEGIN
    SELECT plot_id INTO conflicting_plot_id
    FROM plot
    WHERE plot_id != NEW.plot_id
      AND ST_Intersects(boundary, NEW.boundary)
      AND NOT ST_Touches(boundary, NEW.boundary)
    LIMIT 1;

    IF conflicting_plot_id IS NOT NULL THEN
        RAISE EXCEPTION 'Spatial overlap detected: plot boundary intersects with existing plot_id % without touching cleanly at boundary.', conflicting_plot_id
            USING ERRCODE = '23P01'; -- exclusionary violation
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_plot_overlap ON plot;
CREATE TRIGGER trg_check_plot_overlap
    BEFORE INSERT OR UPDATE OF boundary ON plot
    FOR EACH ROW
    EXECUTE FUNCTION check_plot_overlap();


-- 2. Registry Status History Trigger
CREATE OR REPLACE FUNCTION log_registry_status_history()
RETURNS TRIGGER AS $$
DECLARE
    actor_id VARCHAR(64);
    change_reason TEXT;
BEGIN
    IF OLD.legal_status IS DISTINCT FROM NEW.legal_status THEN
        -- Retrieve transaction session variables if set, or default
        actor_id := current_setting('landregistry.current_user', true);
        IF actor_id IS NULL OR actor_id = '' THEN
            actor_id := 'SYSTEM';
        END IF;

        change_reason := current_setting('landregistry.status_reason', true);
        IF change_reason IS NULL OR change_reason = '' THEN
            change_reason := 'Status transition from ' || OLD.legal_status || ' to ' || NEW.legal_status;
        END IF;

        INSERT INTO registry_status_history (
            registry_id,
            old_status,
            new_status,
            changed_by,
            reason,
            changed_at
        ) VALUES (
            NEW.registry_id,
            OLD.legal_status,
            NEW.legal_status,
            actor_id,
            change_reason,
            CURRENT_TIMESTAMP
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_registry_status_history ON registry_entry;
CREATE TRIGGER trg_registry_status_history
    AFTER UPDATE OF legal_status ON registry_entry
    FOR EACH ROW
    EXECUTE FUNCTION log_registry_status_history();


-- 3. Block Orders on Non-Clear Plots Trigger
CREATE OR REPLACE FUNCTION check_plot_clear_for_orders()
RETURNS TRIGGER AS $$
DECLARE
    plot_status legal_status_enum;
BEGIN
    SELECT legal_status INTO plot_status
    FROM registry_entry
    WHERE plot_id = NEW.plot_id;

    IF plot_status IS NULL THEN
        RAISE EXCEPTION 'Plot % is not registered in the land registry.', NEW.plot_id
            USING ERRCODE = '23503';
    END IF;

    IF plot_status != 'Clear' THEN
        RAISE EXCEPTION 'Orders cannot be placed on plot % because its legal status is %, not Clear.', NEW.plot_id, plot_status
            USING ERRCODE = '22000';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_block_orders_on_unclear_plots ON order_book;
CREATE TRIGGER trg_block_orders_on_unclear_plots
    BEFORE INSERT ON order_book
    FOR EACH ROW
    EXECUTE FUNCTION check_plot_clear_for_orders();
