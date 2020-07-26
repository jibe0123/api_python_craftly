from flask import Blueprint, jsonify
from extensions import db

bp = Blueprint('bp', __name__)


@bp.route('/create_proposal/<string:user_id>/<string:proposal_id>/<string:type>')
def create_proposal(user_id, proposal_id, type):
    if type == 'offer':
        db.graph.run("MERGE (U1:user{name:%s}) MERGE (R:proposal{name:%s}) MERGE m=(U1)-[:O]->(R)" % (
            user_id, proposal_id))
        return jsonify('proposal %s created' % user_id)
    elif type == 'need':
        db.graph.run("MERGE (U:user{name:%s}) MERGE (R:proposal{name:%s}) MERGE m=(R)-[:N]->(U)" % (
            user_id, proposal_id))
        return jsonify('proposal %s created' % user_id)


@bp.route('/get_match/<string:user_id>')
def get_match(user_id):
    return jsonify(db.graph.run(
        "MATCH m=(a:user)-[:O]->()-[*]->()-[:N]->(a:user) WHERE a.name=%s RETURN [n in nodes(m)|n.name] as match" % user_id).data())


@bp.route('/list_proposal')
def list_proposal():
    return jsonify(db.graph.run("MATCH (n:proposal) RETURN n LIMIT 25").data())
