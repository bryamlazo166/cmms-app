import logging
import traceback

from flask import jsonify

from database import db

DEFAULT_LOGGER = logging.getLogger(__name__)


def _safe_log_error(logger, message):
    (logger or DEFAULT_LOGGER).error(message)


def create_entry(Model, data, required_fields, logger=None):
    try:
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing {field}"}), 400

        new_entry = Model(**data)
        db.session.add(new_entry)
        db.session.commit()
        return jsonify(new_entry.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        _safe_log_error(logger, f"Error creating {Model.__name__}: {e}")
        return jsonify({"error": str(e)}), 500


def get_entries(Model):
    if hasattr(Model, 'name'):
        entries = Model.query.order_by(Model.name).all()
    else:
        entries = Model.query.order_by(Model.id).all()
    return jsonify([entry.to_dict() for entry in entries])


def update_entry(Model, entry_id, data, logger=None):
    try:
        entry = Model.query.get(entry_id)
        if not entry:
            return jsonify({"error": f"{Model.__name__} with ID {entry_id} not found"}), 404

        for key, value in data.items():
            if hasattr(entry, key):
                if isinstance(value, str) and value.strip() == "":
                    value = None
                setattr(entry, key, value)

        db.session.commit()
        return jsonify(entry.to_dict())
    except Exception as e:
        db.session.rollback()
        _safe_log_error(logger, f"Update Error: {e}")
        return jsonify({"error": str(e)}), 500


def delete_entry(Model, entry_id, logger=None):
    try:
        entry = Model.query.get(entry_id)
        if not entry:
            return jsonify({"error": f"{Model.__name__} with ID {entry_id} not found"}), 404

        db.session.delete(entry)
        db.session.commit()
        return jsonify({"message": "Deleted successfully"})
    except Exception as e:
        db.session.rollback()
        _safe_log_error(logger, f"Delete Error: {e}")
        return jsonify({"error": str(e)}), 500
