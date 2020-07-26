# note: these are integration tests bc it tests with a live db
# tests are written with reads via cypher
# the primary reason for this is that
# in production direct cypher queries are likely to be faster

import pytest
from py2neo.types import Node
import arrow 
from mock import patch, MagicMock

# _db used in class level teardown
# bc using the db-fixture there does not work
# https://docs.pytest.org/en/latest/xunit_setup.html#class-level-setup-teardown
from extensions import db as _db

# broken into multiple lines to try to organize similar logic
# for the future this could be modularized further
from models import Client, Onboard, BuildClientOnboard
from models import GenericProcess, GenericStep, GenericDocument, BuildGenericProcess
from models import BuildOnboardGenericProcess
from models import Activity, Action, BuildOnboardActivity, BuildAction
from models import UpdateClientOnboard
from models import Company, Employee, BuildEmployeeCompany
from models import Project, BuildEmployeeInvolvement, UpdateEmployeeAccess
from models import Application, Database
from models import BuildCrmDatabase, BuildErpDatabase, BuildComplianceDatabase
from models import EmployeeAppAccess


class TestClient(object):

    @classmethod
    def setup_class(cls):
        '''for some reason this first setup_class does not work with a call to Client.create'''
        cls.LABELS = ['Client', 'Person']
        cls.NUM_PROPERTIES = 2
        cls.NUM_CLIENTS = 3

        cls.COMPANY_ID = 'fake_company_id'
        cls.COMPANY_NAME = 'fake_company_name'

        cls.COMPANY_ID_0 = 'another-test-comp-id'
        cls.COMPANY_NAME_0 = 'another-test-comp-name'

        cls.COMPANY_ID_1 = 'one-more-test-comp-id'
        cls.COMPANY_NAME_1 = 'one-more-test-comp-name'

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (c:Client) "
            "detach delete c"
        ))

    def test_create(self, db):

        self.client = BuildClientOnboard(self.COMPANY_ID, self.COMPANY_NAME)
        self.client.init_rels()

        cursor = db.graph.run((
            "match (c:Client) "
            "where c.company_id='%s' " 
            "return c AS client" % self.COMPANY_ID
        ))

        assert cursor.forward() == 1

        result = cursor.current()['client']

        assert result['company_id'] == self.COMPANY_ID
        assert result['company_name'] == self.COMPANY_NAME
        assert all([label in result.labels() for label in self.LABELS])
        assert len(result.viewkeys()) == self.NUM_PROPERTIES

    def test_list_all(self):

        self.new_client_0 = BuildClientOnboard(self.COMPANY_ID_0, self.COMPANY_NAME_0)
        self.new_client_0.init_rels()
        self.new_client_1 = BuildClientOnboard(self.COMPANY_ID_1, self.COMPANY_NAME_1)
        self.new_client_1.init_rels()

        client_list = Client.list_all()

        assert len(client_list) == self.NUM_CLIENTS

    def test_list_all_with_compliance_status(self):

        clients_with_compliance = Client.list_all_with_compliance_status()

        assert len(clients_with_compliance) == self.NUM_CLIENTS
        for result in clients_with_compliance:
            assert result.get('client') is not None
            assert result.get('completed') is not None
            assert result.get('valid_onboard') is not None


class TestOnboard(object):

    def test_create(self, db):

        NUM_PROPERTIES = 3

        onboard = Onboard.create()

        cursor = db.graph.run((
                    "match (o:Onboard) "
                    "return o AS onboard"
                ))
        cursor.forward()

        result = cursor.current()['onboard']

        assert result['completed'] == False
        assert result['valid_onboard'] == True
        assert arrow.get(result['time_started'])
        assert result['time_completed'] is None
        assert len(result.viewkeys()) == NUM_PROPERTIES

        db.graph.run((
                    "match (o:Onboard) "
                    "delete o"
                ))

    @patch('models.Onboard.select')
    def test_average_time_to_completion(self, select_patch):

        AVERAGE_TTC = 3 # in this case, by design (see loop below)

        result_mocks = [MagicMock() for i in range(3)]

        a = arrow.utcnow()
        for counter, result_mock in enumerate(result_mocks):
            result_mock.time_created = a.timestamp
            result_mock.time_completed = a.timestamp + 2 * counter + 1

        select_patch.return_value = result_mocks

        average_ttc = Onboard.compute_average()

        assert average_ttc == AVERAGE_TTC

    @patch('models.Onboard.select')
    def test_average_time_to_completion_is_None_when_time_completed_not_present(self, select_patch):

        AVERAGE_TTC = None

        result_mocks = [MagicMock() for i in range(3)]

        a = arrow.utcnow()
        for counter, result_mock in enumerate(result_mocks):
            result_mock.time_created = a.timestamp
            result_mock.time_completed = None

        select_patch.return_value = result_mocks

        average_ttc = Onboard.compute_average()

        assert average_ttc == AVERAGE_TTC

    def test_onboard_has_activity_rel(self, db):
        activity = Activity.create()
        onboard = Onboard.create()

        onboard.has_activity.add(activity)

        db.graph.push(onboard)

        cursor = db.graph.run((
            "match (o:Onboard)-[:HAS_ACTIVITY]->(a) "
            "return o, a"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['o'] is not None
        assert cursor.current()['a'] is not None
        assert cursor.forward() == 0

        db.graph.run("match (n) detach delete n")


class TestBuildClientOnboard(object):

    def test_initialize_new_client(self, db):

        COMPANY_ID = 'new_company_id'
        COMPANY_NAME = 'new_company_name'
        REL_TYPE = 'HAS_ONBOARD'

        build_client = BuildClientOnboard(COMPANY_ID, COMPANY_NAME)
        build_client.init()

        cursor = db.graph.run((
                "match (c:Client)-[r:%s]->(o) "
                "where c.company_id='%s' "
                "return c, r, o" % (REL_TYPE, COMPANY_ID)
            ))
        cursor.forward()

        client = cursor.current()['c']
        has_onboard = cursor.current()['r']
        onboard = cursor.current()['o']

        assert client is not None
        assert onboard is not None
        assert REL_TYPE in has_onboard.types()

        db.graph.run((
                "match (c:Client)-[r:%s]->(o) "
                "where c.company_id='%s' "
                "delete c, r, o" % (REL_TYPE, COMPANY_ID)
            ))


class TestGenericProcess(object):

    def test_create(self, db):

        LABELS = ['GenericProcess']

        process = GenericProcess.create()

        cursor = db.graph.run((
            "match (p:GenericProcess) "
            "return p"
        ))
        cursor.forward()

        result = cursor.current()['p']
        assert all([label in result.labels() for label in LABELS])

        db.graph.run((
            "match (p:GenericProcess) "
            "delete p"
        ))


class TestGenericStep(object):

    @classmethod
    def setup_class(cls):
        cls.NUM_PROPERTIES = 3
        cls.TASK_NAME = 'some-step-name'
        cls.STEP_NUMBER = 201
        cls.DURATION = 12
        cls.step = GenericStep.create(cls.TASK_NAME, cls.STEP_NUMBER, cls.DURATION)

    @classmethod
    def teardown_class(cls):
        _db.graph.run("match (s:GenericStep) detach delete s")

    def test_create(self, db):   

        cursor = db.graph.run("match (s:GenericStep) return s")
        cursor.forward()

        result = cursor.current()['s']
        assert result['task_name'] == self.TASK_NAME
        assert result['step_number'] == self.STEP_NUMBER
        assert result['duration'] == self.DURATION
        assert len(result.viewkeys()) == self.NUM_PROPERTIES

    def test_all_method_returns_array_of_proper_length(self, db):

        GenericStep.create('task-a', 0, 15)
        GenericStep.create('task-b', 0, 30)

        all_steps = GenericStep.all()

        assert len(all_steps) == 1 + 2 # 1 from setup, 2 here

    def test_get_by_step_number(self):

        step = GenericStep.get_by_step_number(self.STEP_NUMBER)

        assert step == self.step


class TestGenericDocumentNode(object):

    @classmethod
    def setup_class(cls):
        cls.DOCUMENT_ID = 'test-doc-uuid'
        cls.DOCUMENT_TYPE = 'docx is dead'
        cls.document = GenericDocument.create(cls.DOCUMENT_ID, cls.DOCUMENT_TYPE)

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (d:GenericDocument) "
            "delete d"
        ))

    def test_generic_document_node(self, db):

        cursor = db.graph.run((
            "match (d:GenericDocument) "
            "return d"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['d']['document_id'] == self.DOCUMENT_ID
        assert cursor.current()['d']['document_type'] == self.DOCUMENT_TYPE


class TestBuildGenericProcess(object):

    @classmethod
    def setup_class(cls):
        cls.generic = BuildGenericProcess()
        cls.generic.init()

        cls.NUM_STEPS = 5
        cls.STEPS_WITH_DEPENDS = {3, 4}
        cls.DEPENDENCIES = {3: set([0, 1, 2]), 4: set([0, 1, 2, 3])}

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (d)<-[:REQUIRES_DOCUMENT]-(p:GenericProcess)-[:NEXT*]->(s) "
            "detach delete s, p, d"
        ))

    def test_next_rel(self, db):

        cursor = db.graph.run((
            "match (:GenericProcess)-[:NEXT*]->(s) "
            "return s order by s.step_number"
        ))
        num_results = 0
        for counter, result in enumerate(cursor):
            assert result['s']['step_number'] == counter
            num_results += 1

        assert num_results == self.NUM_STEPS 

    def test_has_step_rel(self, db):

        cursor = db.graph.run((
            "match (:GenericProcess)-[:HAS_STEP*]->(s) "
            "return s order by s.step_number"
        ))
        num_results = 0
        for counter, result in enumerate(cursor):
            assert result['s']['step_number'] == counter
            num_results += 1

        assert num_results == self.NUM_STEPS

    def test_first_step_rel(self, db):

        cursor = db.graph.run((
            "match (:GenericProcess)-[:FIRST_STEP]->(s) "
            "return s"
        ))
        cursor.forward()

        assert cursor.current()['s']['step_number'] == 0
        assert cursor.forward() == 0

    def test_last_step_rel(self, db):

        cursor = db.graph.run((
            "match (:GenericProcess)-[:LAST_STEP]->(s) "
            "return s"
        ))
        cursor.forward()

        assert cursor.current()['s']['step_number'] == self.NUM_STEPS - 1
        assert cursor.forward() == 0

    def test_get_steps_with_depends(self, db):

        cursor = db.graph.run((
            "match (:GenericProcess)-[:HAS_STEP*]->(s), "
            "(s)-[:DEPENDS_ON*]->(d) "
            "return collect(distinct s.step_number) AS steps"
        ))
        assert cursor.forward() == 1

        assert set(cursor.current()['steps']) == self.STEPS_WITH_DEPENDS

    def test_depends_on_rel(self, db):

        cursor = db.graph.run((
            "match (:GenericProcess)-[:HAS_STEP*]->(s), "
            "(s)-[:DEPENDS_ON*]->(d)"
            "return s , d order by s.step_number"
        ))

        results = {}
        for result in cursor:
            if results.get(result['s']['step_number']) is None:
                results[result['s']['step_number']] = set({}) 
            results[result['s']['step_number']].add(result['d']['step_number'])

        assert results == self.DEPENDENCIES

    def test_requires_document_rel(self, db):

        cursor = db.graph.run((
            "match (:GenericProcess)-[:REQUIRES_DOCUMENT]->(d) "
            "return d"
        ))

        assert len([_ for _ in cursor]) == len(self.generic.document_metadata)
        assert cursor.current()['d'].has_label('GenericDocument')

    def test_docs_steps_structure_for_step_rel(self, db):

        cursor = db.graph.run((
            "match (:GenericStep)<-[:FOR_STEP]-(d) "
            "return d"
        ))

        assert len([_ for _ in cursor]) == len(self.generic.document_metadata)
        assert cursor.current()['d'].has_label('GenericDocument')


class TestBuildOnboardGenericProcess(object):

    @classmethod
    def setup_class(cls):

        cls.COMPANY_ID = 'some-id-for-company'
        cls.COMPANY_NAME = 'some-comp-name'

        cls.client = BuildClientOnboard(cls.COMPANY_ID, cls.COMPANY_NAME)
        cls.client.init()
        
        cls.generic = BuildGenericProcess()
        cls.generic.init()
        
        cls.client_onboard = BuildOnboardGenericProcess(cls.COMPANY_ID)
        cls.client_onboard.init()

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (c:Client), (o:Onboard), (p:GenericProcess), (s:GenericStep), (d:GenericDocument) "
            "detach delete c, o, p, s, d"
        ))

    def test_must_follow_rel(self, db):

        cursor = db.graph.run((
            "match (c:Client)-[:HAS_ONBOARD]->()-[:MUST_FOLLOW]->(p) "
            "where c.company_id='%s' "
            "return c, p" % self.COMPANY_ID
        ))

        assert cursor.forward() == 1
        
        client = cursor.current()['c']
        process = cursor.current().get('p')

        assert client['company_id'] == self.COMPANY_ID
        assert process is not None

        assert cursor.forward() == 0

    def test_missing_docs_rels(self, db):

        cursor = db.graph.run((
            "match (:Onboard)-[:MISSING_DOCUMENT]->(d) "
            "return d"
        ))

        assert len([_ for _ in cursor]) == len(self.generic.document_metadata)
        assert cursor.current()['d'].has_label('GenericDocument')


class TestActivityNode(object):

    @classmethod
    def setup_class(cls):
        cls.CID = 'companyid'

        Onboard.create()
        cls.activity = Activity.create()
        cls.action = Action.create(cls.CID)

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (a:Activity), (o:Onboard), (ac:Action) "
            "detach delete a, o, ac"
        ))

    def test_activity_node(self, db):
        cursor = db.graph.run((
            "match (a:Activity) "
            "return a"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['a'] is not None
        assert cursor.forward() == 0

    def test_action_taken_rel(self, db):
        self.activity.action_taken.add(self.action)
        db.graph.push(self.activity)

        cursor = db.graph.run((
            "match (:Activity)-[:ACTION_TAKEN]->(ac) "
            "return ac"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['ac'] is not None
        assert cursor.forward() == 0

    def test_first_action_rel(self, db):
        self.activity.first_action.add(self.action)
        db.graph.push(self.activity)

        cursor = db.graph.run((
            "match (:Activity)-[:FIRST_ACTION]->(ac) "
            "return ac"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['ac'] is not None
        assert cursor.forward() == 0

    def test_last_action_rel(self, db):
        self.activity.last_action.add(self.action)
        db.graph.push(self.activity)

        cursor = db.graph.run((
            "match (:Activity)-[:LAST_ACTION]->(ac) "
            "return ac"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['ac'] is not None
        assert cursor.forward() == 0


class TestActionNode(object):

    @classmethod
    def setup_class(cls):
        cls.CID = 'companyid'
        cls.CNAME = 'comp-name'

        cls.action = Action.create(cls.CID)
        cls.new_action = Action.create(cls.CID)
        cls.step = GenericStep.create('test_task', 10, 4052)

        cls.STEP_NUMBER = 33
        cls.DURATION = 12322
        cls.new_step = GenericStep.create('new_task', cls.STEP_NUMBER, cls.DURATION)

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (a:Action), (gs:GenericStep), (c:Client), (o:Onboard), (ac:Activity) "
            "detach delete a, gs, c, o, ac"
        ))

    def test_action_node(self, db):
        cursor = db.graph.run((
            "match (ac:Action) "
            "return ac"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['ac'] is not None
        assert arrow.get(cursor.current()['ac']['taken_at'])
        assert cursor.forward() == 1
        assert cursor.forward() == 0

    def test_action_node_timestamps_load_with_arrow(self, db):
        cursor = db.graph.run((
            "match (ac:Action) "
            "return ac"
        ))

        assert cursor.forward() == 1
        assert arrow.get(cursor.current()['ac']['taken_at'])
        assert cursor.forward() == 1
        assert arrow.get(cursor.current()['ac']['taken_at'])
        assert cursor.forward() == 0

    def test_that_action_node_number_defaults_to_null_with_no_structure(self, db):
        cursor = db.graph.run((
            "match (ac:Action) "
            "return ac"
        ))
        assert cursor.forward() == 1
        assert cursor.current()['ac']['number'] is None
        assert cursor.forward() == 1
        assert cursor.current()['ac']['number'] is None

    def test_action_taken_rel(self, db):
        self.action.action_taken.add(self.new_action)
        db.graph.push(self.action)

        cursor = db.graph.run((
            "match (:Action)-[:ACTION_TAKEN]->(ac) "
            "return ac"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['ac'] is not None
        assert cursor.forward() == 0

    def test_has_completed_rel(self, db):
        self.action.has_completed.add(self.step)
        db.graph.push(self.action)

        cursor = db.graph.run((
            "match (:Action)-[:HAS_COMPLETED]->(step) "
            "return step"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['step'] is not None
        assert cursor.forward() == 0

    def test_add_has_completed_rel_without_supporting_structure(self, db):
        with pytest.raises(LookupError) as exc_info:
            self.action.add_has_completed_rel(self.CID, self.STEP_NUMBER)
    
        assert exc_info.match('required graph structure missing')        

    def test_add_has_completed_rel_with_supporting_structure(self, db):
        build_client = BuildClientOnboard(self.CID, self.CNAME)
        build_client.init()
        build_activity = BuildOnboardActivity(self.CID)
        build_activity.init()

        self.action.add_has_completed_rel(self.CID, self.STEP_NUMBER)

        cursor = db.graph.run((
            "match (step:GenericStep {step_number: %d}) "
            "match (step)<-[:HAS_COMPLETED]-(action) "
            "return action" % self.STEP_NUMBER
        ))

        assert cursor.forward() == 1
        assert cursor.current()['action'] is not None
        assert cursor.forward() == 0

        db.graph.run((
            "match (c:Client), (o:Onboard), (a:Activity) "
            "detach delete c, o, a"
        ))

    def test_is_client_onboard_structure_built_is_falsey(self):

        assert not self.action._is_client_onboard_structure_built(self.CID)

    def test_is_onboard_activity_structure_built_is_falsey(self):

        assert not self.action._is_onboard_activity_structure_built(self.CID)

    def test_get_num_actions_with_no_supporting_structure(self, db):

        assert self.action.get_num_actions(self.CID) == None

    def test_is_client_onboard_structure_built_is_truthy(self):
        build_client = BuildClientOnboard(self.CID, self.CNAME)
        build_client.init()
        build_activity = BuildOnboardActivity(self.CID)
        build_activity.init()
        build_action = BuildAction(self.CID)

        assert self.action._is_client_onboard_structure_built(self.CID)

    def test_is_onboard_activity_structure_built_is_truthy(self):

        assert self.action._is_onboard_activity_structure_built(self.CID)

    def test_get_num_actions_with_support_structures(self, db):
        build_action = BuildAction(self.CID)
        NUM_ACTIONS = 10
        for i in range(NUM_ACTIONS):
            build_action.new_action(self.STEP_NUMBER)
        assert self.action.get_num_actions(self.CID) == NUM_ACTIONS

    def test_action_node_number_with_supporting_structure(self, db):
        db.graph.run((
            "match (a:Action) "
            "detach delete a"
        ))

        build_client = BuildClientOnboard('new', 'newcname')
        build_client.init()

        build_activity = BuildOnboardActivity('new')
        build_activity.init()

        build_action = BuildAction('new')
        build_action.new_action(self.STEP_NUMBER)
        build_action.new_action(self.STEP_NUMBER)
        build_action.new_action(self.STEP_NUMBER)

        cursor = db.graph.run((
            "match (ac:Action) "
            "return ac"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['ac']['number'] == 0
        assert cursor.forward() == 1
        assert cursor.current()['ac']['number'] == 1
        assert cursor.forward() == 1
        assert cursor.current()['ac']['number'] == 2
        assert cursor.forward() == 0


class TestBuildOnboardActivity(object):

    @classmethod
    def setup_class(cls):
        cls.CID = 'cid'
        cls.client = BuildClientOnboard(cls.CID, 'cname')
        cls.client.init()
        cls.onboard_activity = BuildOnboardActivity(cls.CID)
        cls.onboard_activity.init()

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (o:Onboard), (c:Client), (a:Activity) "
            "detach delete o, c, a"
        ))

    def test_onboard_activity_basic_structure_traversal(self, db):
        cursor = db.graph.run((
            "match (:Client)-[:HAS_ONBOARD]->()-[:HAS_ACTIVITY]->(a) "
            "return a"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['a'] is not None
        assert cursor.forward() == 0


class TestBuildAction(object):

    @classmethod
    def setup_class(cls):
        cls.CID = 'cid'
        cls.client = BuildClientOnboard(cls.CID, 'cname')
        cls.client.init()
        cls.onboard_activity = BuildOnboardActivity(cls.CID)
        cls.onboard_activity.init()
        cls.build_action = BuildAction(cls.CID)

        cls.STEP_NUMBER = 9523
        cls.step = GenericStep.create('taskname', cls.STEP_NUMBER, 1235)

        cls.build_generic = BuildGenericProcess()
        cls.build_generic.init()

        # completed dependencies
        cls.STEPS_COMPLETED = [0, 4]
        for step in cls.STEPS_COMPLETED:
            cls.build_action.new_action(step)

        cls.NUM_DEPENDS_MAP = [0, 0, 0, 3, 4]
        cls.DOCUMENT_ID_TO_SUBMIT = 1

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (o:Onboard), (c:Client), (a:Activity), (ac:Action), (gs:GenericStep), (p:GenericProcess), (d:GenericDocument) "
            "detach delete o, c, a, ac, gs, p, d"
        ))

    def first_action_helper(self):
        '''check first action structure is in place'''
        cursor = _db.graph.run((
            "match (:Client {company_id: '%s'})-[:HAS_ONBOARD]->()-[:HAS_ACTIVITY]->(activity) "
            "match (activity)-[:ACTION_TAKEN]->(action_taken) "
            "match (activity)-[:FIRST_ACTION]->(first) "
            "match (activity)-[:LAST_ACTION]->(last) "
            "return action_taken, first, last" % self.CID
        ))

        assert cursor.forward() == 1
        assert cursor.current()['action_taken'] is not None
        assert cursor.current()['first'] is not None
        assert cursor.current()['last'] is not None
        assert cursor.forward() == 0

    def check_first_action_not_last_action_helper(self):
        '''check last action no longer with first action'''
        cursor = _db.graph.run((
            "match (:Activity)-[:FIRST_ACTION]->(first) "
            "match (first)<-[:LAST_ACTION]-(activity) "
            "return activity"
        ))
        assert cursor.forward() == 0

    def clear_action_nodes_and_rels(self):
        '''clean up action nodes'''
        cursor = _db.graph.run((
            "match (ac:Action) "
            "detach delete ac"
        ))
        _db.graph.pull(self.build_action.activity)
        return 'cleaned'

    def test_is_first_action_returns_truthy(self, db):
        self.clear_action_nodes_and_rels()
        assert self.build_action._is_first_action()

    def test_add_first_action(self, db):
        self.build_action._add_first_action()
        self.first_action_helper()

    def test_is_first_action_returns_falsey(self, db):
        assert not self.build_action._is_first_action()

    def test_get_and_move_last_action(self, db):
        new_action = Action.create(self.CID)
        db.graph.push(new_action)
        last_action = self.build_action._get_and_move_last_action(new_action)
        last_action.action_taken.add(new_action)
        db.graph.push(last_action)

        self.check_first_action_not_last_action_helper()

        # check last action is tied to the new action
        cursor = db.graph.run((
            "match (:Activity)-[:FIRST_ACTION]->(first) "
            "match (first)-[:ACTION_TAKEN]->(last) "
            "match (last)<-[:LAST_ACTION]-(activity) "
            "return activity"
        ))
        assert cursor.forward() == 1
        assert cursor.forward() == 0

        self.clear_action_nodes_and_rels()

    def test__add_next_action(self, db):
        self.build_action._add_first_action()
        self.build_action._add_next_action()
        self.build_action._add_next_action()

        cursor = db.graph.run((
            "match (:Client {company_id: '%s'})-[:HAS_ONBOARD]->()-[:HAS_ACTIVITY]->()-[:ACTION_TAKEN*]->(action) "
            "return action" % self.CID
        ))
        results = [_['action'] for _ in cursor]
        
        assert len(results) == 3
        assert all([isinstance(_, Node) for _ in results])

        self.clear_action_nodes_and_rels()

    def test__new_action_properly_builds_first_action(self, db):
        self.build_action._new_action()
        self.first_action_helper()

        self.clear_action_nodes_and_rels()

    def test__new_action_properly_builds_more_actions(self, db):
        self.build_action._new_action()
        self.build_action._new_action()
        self.build_action._new_action()

        self.check_first_action_not_last_action_helper()

        cursor = db.graph.run((
            "match (:Client {company_id: '%s'})-[:HAS_ONBOARD]->()-[:HAS_ACTIVITY]->(activity) "
            "match (activity)-[:FIRST_ACTION]->(first) "
            "match (first)-[:ACTION_TAKEN]->(second) "
            "match (second)-[:ACTION_TAKEN]->(third) "
            "match (third)<-[:LAST_ACTION]-(_activity) "
            "return activity, _activity" % self.CID
        ))

        assert cursor.forward() == 1
        assert cursor.current()['activity'] == cursor.current()['_activity']
        assert cursor.forward() == 0

        self.clear_action_nodes_and_rels()

    def test_new_action_properly_builds_first_action(self, db):
        self.build_action.new_action(self.STEP_NUMBER)
        self.first_action_helper()

        cursor = db.graph.run((
            "match (:Activity)-[:FIRST_ACTION]->()-[:HAS_COMPLETED]->(gs) "
            "return gs"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['gs']['step_number'] == self.STEP_NUMBER
        assert cursor.forward() == 0

        self.clear_action_nodes_and_rels()

    def test_new_action_properly_builds_more_actions(self, db):

        self.build_action.new_action(self.STEP_NUMBER)
        self.build_action.new_action(self.STEP_NUMBER)
        self.build_action.new_action(self.STEP_NUMBER)

        self.check_first_action_not_last_action_helper()

        cursor = db.graph.run((
            "match (:Client {company_id: '%s'})-[:HAS_ONBOARD]->()-[:HAS_ACTIVITY]->(activity) "
            "match (activity)-[:FIRST_ACTION]->(first) "
            "match (first)-[:ACTION_TAKEN]->(second) "
            "match (second)-[:ACTION_TAKEN]->(third) "
            "match (third)<-[:LAST_ACTION]-(_activity) "
            "match (third)-[:HAS_COMPLETED]->(gs) "
            "return activity, _activity, gs" % self.CID
        ))

        assert cursor.forward() == 1
        assert cursor.current()['activity'] == cursor.current()['_activity']
        assert cursor.current()['gs']['step_number'] == self.STEP_NUMBER
        assert cursor.forward() == 0

        self.clear_action_nodes_and_rels()

    def test_new_action_with_steps(self, db):

        for step in self.STEPS_COMPLETED:
            self.build_action.new_action(step)

        cursor = db.graph.run((
            "match (:Action)-[:HAS_COMPLETED]->(s) "
            "return s order by s.step_number"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['s']['step_number'] == self.STEPS_COMPLETED[0]
       
        assert cursor.forward() == 1
        assert cursor.current()['s']['step_number'] == self.STEPS_COMPLETED[1]

        assert cursor.forward() == 0

        self.clear_action_nodes_and_rels()

    def test_each_step_has_the_correct_number_of_dependencies(self):

        for i, num_depends in zip(range(5), self.NUM_DEPENDS_MAP):
            assert self.build_action._num_dependencies(i) == num_depends

    def test_that_first_step_is_completed_dependency_for_the_fourth_step(self):

        for step in self.STEPS_COMPLETED:
            self.build_action.new_action(step)

        assert 0 in self.build_action._completed_dependencies(3)

        self.clear_action_nodes_and_rels()

    def test_that_dependencies_are_not_satisfied_for_the_fourth_step(self):

        for step in self.STEPS_COMPLETED:
            self.build_action.new_action(step)

        assert not self.build_action._depends_satisfied(3)

        self.clear_action_nodes_and_rels()

    def test_that_dependencies_are_satisfied_for_the_fourth_step(self):

        self.build_action.new_action(0)
        self.build_action.new_action(1)
        self.build_action.new_action(2)

        assert self.build_action._depends_satisfied(3)

        self.clear_action_nodes_and_rels()

    def test_that_dependencies_are_not_satisfied_for_the_fifth_step(self):

        self.build_action.new_action(0)
        self.build_action.new_action(1)
        self.build_action.new_action(2)

        assert not self.build_action._depends_satisfied(4)

        self.clear_action_nodes_and_rels()

    def test_that_dependencies_are_satisfied_for_the_fifth_step(self):

        self.build_action.new_action(0)
        self.build_action.new_action(1)
        self.build_action.new_action(2)
        self.build_action.new_action(3)

        assert self.build_action._depends_satisfied(4)

        self.clear_action_nodes_and_rels()

    def test_marking_a_step_as_invalid(self, db):

        STEP = 3
        VALID = False

        self.build_action._mark_step_invalid(STEP)

        cursor = db.graph.run((
            "match (o:Onboard)-[:INVALID]->(gs) "
            "return gs, o"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['gs']['step_number'] == STEP
        assert cursor.current()['o']['valid_onboard'] == VALID
        assert cursor.forward() == 0 

    def test_that_a_step_with_no_dependencies_gets_marked_correctly_with_aware_step_completion(self, db):
        db.graph.run((
            "match (o:Onboard)-[i:INVALID]->() "
            "set o.valid_onboard=true "
            "delete i"
        ))
        db.graph.pull(self.build_action.onboard)
        assert self.build_action.onboard.valid_onboard # make sure property change is available

        num_steps = 3

        for i in range(num_steps):
            self.build_action._dependency_aware_mark_step_complete(i)

        cursor = db.graph.run((
            "match (o:Onboard)-[:HAS_COMPLETED]->(gs) "
            "return o.valid_onboard AS valid, count(gs) AS num_complete"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['valid'] == True
        assert cursor.current()['num_complete'] == num_steps
        assert cursor.forward() == 0

        cursor_0 = db.graph.run((
            "match (o:Onboard)-[:INVALID]->(gs) "
            "return gs"
        ))

        assert cursor_0.forward() == 0

    def test_that_onboard_remains_valid_for_a_step_with_satisfied_dependencies(self, db):
        # TODO this functionality changed bc of _completed_dependencies
        # it now finds the completed dependencies off action nodes
        # these tests need to be changed appropriately
        num_steps = 2

        for i in range(num_steps):
            self.build_action._dependency_aware_mark_step_complete(i + 3)

        cursor = db.graph.run((
            "match (o:Onboard)-[:HAS_COMPLETED]->(gs) "
            "return o.valid_onboard AS valid, count(gs) AS num_complete"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['valid'] == True
        assert cursor.current()['num_complete'] == 5
        assert cursor.forward() == 0

        cursor_0 = db.graph.run((
            "match (o:Onboard)-[:INVALID]->(gs) "
            "return gs"
        ))

        assert cursor_0.forward() == 0

    def test_that_onboard_gets_invalidated_if_a_step_is_completed_before_a_dependency(self, db):

        NUM_INVALID = 2
        NUM_COMPLETE = 3
        VALID = False

        db.graph.run((
            "match (:Action)-[c:HAS_COMPLETED]->() "
            "delete c"
        ))
        db.graph.pull(self.build_action.onboard)
        assert len([_ for _ in self.build_action.onboard.has_completed]) == 0

        assert False

        self.build_action._dependency_aware_mark_step_complete(3)
        self.build_action._dependency_aware_mark_step_complete(4)
        self.build_action._dependency_aware_mark_step_complete(1)

        cursor = db.graph.run((
            "match (o:Onboard)-[r:HAS_COMPLETED|INVALID]->() "
            "return o.valid_onboard as valid, type(r) as type, count(r) as count order by type"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['valid'] == VALID
        assert cursor.current()['count'] == NUM_COMPLETE
        assert cursor.forward() == 1
        assert cursor.current()['valid'] == VALID
        assert cursor.current()['count'] == NUM_INVALID
        assert cursor.forward() == 0

    def test_mark_onboard_as_completed(self, db):

        COMPLETION_STATUS = True

        self.build_action._mark_onboard_complete()

        cursor = db.graph.run((
            "match (o:Onboard) "
            "return o.completed AS c, o.time_completed AS time_completed"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['c'] == COMPLETION_STATUS
        assert arrow.get(cursor.current()['time_completed'])
        assert cursor.forward() == 0

    def test_step_aware_mark_onboard_complete_does_not_mark_onboard_as_complete_if_steps_are_not_complete(self, db):
        # TODO this functionality changed bc of _completed_dependencies
        # it now finds the completed dependencies off action nodes
        # these tests need to be changed appropriately

        COMPLETION_STATUS = False

        # reset some stuff for this test
        db.graph.run((
            "match (o:Onboard)-[c:HAS_COMPLETED]->() "
            "set o.completed=false "
            "delete c"
        ))
        # pull down the change for py2neo
        db.graph.pull(self.build_action.onboard) 

        # mark some steps as complete
        self.build_action._mark_step_complete(1)
        self.build_action._mark_step_complete(2)

        # try to mark onboard as complete (should have no effect)
        self.build_action._step_aware_mark_onboard_complete()

        cursor = db.graph.run((
            "match (o:Onboard) "
            "return o.completed AS completed"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['completed'] == COMPLETION_STATUS
        assert cursor.forward() == 0

    def test_step_aware_mark_onboard_complete_suceeds_if_all_steps_have_been_completed(self, db):
        # TODO this functionality changed bc of _completed_dependencies
        # it now finds the completed dependencies off action nodes
        # these tests need to be changed appropriately

        COMPLETION_STATUS = True

        # reset some stuff for this test
        db.graph.run((
            "match (o:Onboard)-[c:HAS_COMPLETED]->() "
            "set o.completed=false "
            "delete c"
        ))
        # pull down the change for py2neo
        db.graph.pull(self.build_action.onboard) 

        # mark all steps as complete
        for i in range(len(GenericStep.all())):
            self.build_action._mark_step_complete(i)

        # mark onboard as complete
        self.build_action._step_aware_mark_onboard_complete()

        cursor = db.graph.run((
            "match (o:Onboard) "
            "return o.completed AS completed"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['completed'] == COMPLETION_STATUS
        assert cursor.forward() == 0

    def test_that_aware_step_mark_completion_will_NOT_mark_onboard_complete_if_steps_incomplete(self, db):
        # TODO this functionality changed bc of _completed_dependencies
        # it now finds the completed dependencies off action nodes
        # these tests need to be changed appropriately

        COMPLETION_STATUS = False

        db.graph.run((
            "match (o:Onboard)-[c:HAS_COMPLETED]->() "
            "set o.completed=false "
            "delete c"
        ))
        db.graph.pull(self.build_action.onboard)

        self.build_action.aware_mark_step_complete(1)
        self.build_action.aware_mark_step_complete(2)
        self.build_action.aware_mark_step_complete(4)

        cursor = db.graph.run((
            "match (o:Onboard) "
            "return o.completed AS completed"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['completed'] == COMPLETION_STATUS
        assert cursor.forward() == 0

    def test_that_aware_step_mark_completion_DOES_mark_onboard_complete_if_ALL_steps_complete(self, db):
        # TODO this functionality changed bc of _completed_dependencies
        # it now finds the completed dependencies off action nodes
        # these tests need to be changed appropriately

        COMPLETION_STATUS = True

        db.graph.run((
            "match (o:Onboard)-[c:HAS_COMPLETED]->() "
            "set o.completed=false "
            "delete c"
        ))
        db.graph.pull(self.build_action.onboard)

        for i in range(len(GenericStep.all())):
            self.build_action.aware_mark_step_complete(i)

        cursor = db.graph.run((
            "match (o:Onboard) "
            "return o.completed AS completed"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['completed'] == COMPLETION_STATUS
        assert cursor.forward() == 0

    def test_that_onboard_gets_invalidated_if_a_step_is_completed_before_a_dependency_with_aware_mark_step(self, db):
        # TODO this functionality changed bc of _completed_dependencies
        # it now finds the completed dependencies off action nodes
        # these tests need to be changed appropriately

        db.graph.run((
            "match (o:Onboard)-[c:HAS_COMPLETED]->() "
            "match (o)-[i:INVALID]->() "
            "set o.valid_onboard=true "
            "delete c, i"
        ))
        db.graph.pull(self.build_action.onboard)

        NUM_INVALID = 2
        NUM_COMPLETE = 3
        VALID = False

        self.build_action.aware_mark_step_complete(3)
        self.build_action.aware_mark_step_complete(4)
        self.build_action.aware_mark_step_complete(1)

        cursor = db.graph.run((
            "match (o:Onboard)-[r:HAS_COMPLETED|INVALID]->() "
            "return o.valid_onboard as valid, type(r) as type, count(r) as count order by type"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['valid'] == VALID
        assert cursor.current()['count'] == NUM_COMPLETE
        assert cursor.forward() == 1
        assert cursor.current()['valid'] == VALID
        assert cursor.current()['count'] == NUM_INVALID
        assert cursor.forward() == 0

    def test_mark_step_complete(self, db):
        # TODO this functionality changed bc of _completed_dependencies
        # it now finds the completed dependencies off action nodes
        # these tests need to be changed appropriately

        cursor = db.graph.run((
            "match ()-[r:HAS_COMPLETED]->(s) "
            "return r, s order by s.step_number"
        ))

        assert cursor.forward() == 1
        assert self.REL_TYPE in cursor.current()['r'].types()
        assert cursor.current()['s']['step_number'] == self.STEPS_COMPLETED[0]

        assert cursor.forward() == 1
        assert self.REL_TYPE in cursor.current()['r'].types()
        assert cursor.current()['s']['step_number'] == self.STEPS_COMPLETED[1]

        assert cursor.forward() == 0


class TestUpdateClientOnboard(object):
    # TODO: in process of factoring out the step completion stuff
    # this will be trimmed significantly fairly soon
    @classmethod
    def setup_class(cls):

        cls.COMPANY_ID = 'some-id-for-company'
        cls.COMPANY_NAME = 'some-comp-name'

        cls.client = BuildClientOnboard(cls.COMPANY_ID, cls.COMPANY_NAME)
        cls.client.init()
        
        cls.generic = BuildGenericProcess()
        cls.generic.init()
        
        cls.client_onboard = BuildOnboardGenericProcess(cls.COMPANY_ID)
        cls.client_onboard.init()
        
        cls.update_onboard = UpdateClientOnboard(cls.COMPANY_ID)

        cls.DOCUMENT_ID_TO_SUBMIT = 1

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (c:Client), (o:Onboard), (p:GenericProcess), (s:GenericStep), (d:GenericDocument) "
            "detach delete c, o, p, s"
        ))

    def test_that_document_can_be_submitted(self, db):

        self.update_onboard.submit_document(self.DOCUMENT_ID_TO_SUBMIT)

        cursor = db.graph.run((
            "match (:Onboard)-[:SUBMITTED_DOCUMENT]->(d) "
            "return d"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['d']['document_id'] == self.DOCUMENT_ID_TO_SUBMIT
        assert cursor.forward() == 0

    def test_that_is_not_marked_as_missing_when_submitted(self, db):

        cursor = db.graph.run((
            "match (:Onboard)-[:MISSING_DOCUMENT]->(d) "
            "where d.document_id=%d "
            "return d" % self.DOCUMENT_ID_TO_SUBMIT
        ))

        assert cursor.forward() == 0


class TestCompanyNode(object):

    @classmethod
    def setup_class(cls):

        cls.NAME = 'a-company-like-citi-bank'

        cls.company = Company()
        cls.company.push(cls.NAME)

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (c:Company) "
            "delete c"
        ))

    def test_company_node(self, db):

        cursor = db.graph.run((
            "match (c:Company) "
            "return c"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['c']['name'] == self.NAME
        assert cursor.forward() == 0


class TestEmployeeNode(object):

    @classmethod
    def setup_class(cls):

        cls.ID = '1122452335'
        cls.EMAIL = 'gpwn@fuzz.org'
        cls.LABELS = {'Employee', 'Person'}

        cls.employee = Employee()
        cls.employee.push(cls.ID, cls.EMAIL)

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (e:Employee) "
            "delete e"
        ))

    def test_employee_node(self, db):

        cursor = db.graph.run((
            "match (e:Employee) "
            "return e"
        ))

        assert cursor.forward() == 1
        assert set(cursor.current()['e'].labels()) == self.LABELS
        assert cursor.current()['e']['id'] == self.ID
        assert cursor.current()['e']['email'] == self.EMAIL
        assert cursor.forward() == 0


class TestBuildEmployeeCompany(object):

    @classmethod
    def setup_class(cls):

        cls.COMPANY_NAME = 'a-company-like-citi-bank'
        cls.EMPLOYEE_ID = '1122452335'
        cls.EMPLOYEE_EMAIL = 'gpwn@fuzz.org'

        cls.build_employee = BuildEmployeeCompany(
            cls.EMPLOYEE_ID, 
            cls.EMPLOYEE_EMAIL, 
            cls.COMPANY_NAME
        )
        cls.build_employee.init_rels()

        cls.REL_TYPE = 'WORKS_FOR'

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (c:Company), (e:Employee) "
            "detach delete e, c"
        ))

    def test_build_employee(self, db):

        cursor = db.graph.run((
            "match (e:Employee)-[r:WORKS_FOR]->(c) "
            "return e, r, c"
        ))

        assert cursor.forward() == 1
        assert self.REL_TYPE in cursor.current()['r'].types()
        assert cursor.current()['e']['id'] == self.EMPLOYEE_ID
        assert cursor.current()['c']['name'] == self.COMPANY_NAME
        assert cursor.forward() == 0


class TestProjectNode(object):

    @classmethod
    def setup_class(cls):

        cls.LABELS = {'Project'}
        cls.project = Project()
        cls.project.create()

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (p:Project) "
            "delete p"
        ))

    def test_project_node(self, db):

        cursor = db.graph.run((
            "match (p:Project) "
            "return p"
        ))

        assert cursor.forward() == 1
        assert set(cursor.current()['p'].labels()) == self.LABELS
        assert cursor.forward() == 0


class TestBuildEmployeeInvolvement(object):

    @classmethod
    def setup_class(cls):

        cls.CLIENT_ID = 'somecliid'
        cls.CLIENT_NAME = 'some-client-name-aka-company-name'

        cls.build_client = BuildClientOnboard(cls.CLIENT_ID, cls.CLIENT_NAME)
        cls.build_client.init_rels()

        cls.COMPANY_NAME = 'a-company-like-citi-bank'
        cls.EMPLOYEE_ID = '1122452335'
        cls.EMPLOYEE_EMAIL = 'gpwn@fuzz.org'

        cls.build_employee = BuildEmployeeCompany(
            cls.EMPLOYEE_ID, 
            cls.EMPLOYEE_EMAIL, 
            cls.COMPANY_NAME
        )
        cls.build_employee.init_rels()

        cls.employee_involve = BuildEmployeeInvolvement(cls.EMPLOYEE_ID, cls.CLIENT_ID)
        cls.employee_involve.init_rels()

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (co:Company), (e:Employee), (cl:Client), (p:Project), (o:Onboard) "
            "detach delete co, e, cl, p, o"
        ))

    def test_employee_involvement(self, db):

        cursor = db.graph.run((
            "match (e:Employee)-[:WORKED_ON]->(p), (c)<-[:FOR_CLIENT]-(p)-[:FOR_ONBOARD]->(o) "
            "return p, c, o"
        ))

        assert cursor.forward() == 1
        assert isinstance(cursor.current().get('p'), Node)
        assert isinstance(cursor.current().get('c'), Node)
        assert isinstance(cursor.current().get('o'), Node)
        assert cursor.forward() == 0


class TestUpdateEmployeeAccess(object):

    @classmethod
    def setup_class(cls):

        cls.CLIENT_ID = 'somecliid'
        cls.CLIENT_NAME = 'some-client-name-aka-company-name'

        cls.build_client = BuildClientOnboard(cls.CLIENT_ID, cls.CLIENT_NAME)
        cls.build_client.init_rels()

        cls.build_generic = BuildGenericProcess()
        cls.build_generic.init()

        cls.build_cli_onboard = BuildOnboardGenericProcess(cls.CLIENT_ID)
        cls.build_cli_onboard.init_rels()

        cls.COMPANY_NAME = 'a-company-like-citi-bank'
        cls.EMPLOYEE_ID = '1122452335'
        cls.EMPLOYEE_EMAIL = 'gpwn@fuzz.org'

        cls.build_employee = BuildEmployeeCompany(
            cls.EMPLOYEE_ID, 
            cls.EMPLOYEE_EMAIL, 
            cls.COMPANY_NAME
        )
        cls.build_employee.init_rels()

        cls.employee_involve = BuildEmployeeInvolvement(cls.EMPLOYEE_ID, cls.CLIENT_ID)
        cls.employee_involve.init_rels()

        cls.STEP_ACCESSED = 2

        cls.employee_access = UpdateEmployeeAccess(cls.EMPLOYEE_ID)
        cls.employee_access.update_step_access(cls.CLIENT_ID, cls.STEP_ACCESSED)

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (co:Company), (e:Employee), (cl:Client), (p:Project), (o:Onboard) , (g:GenericProcess), (s:GenericStep)"
            "detach delete co, e, cl, p, o, g, s"
        ))

    def test_employee_access(self, db):

        cursor = db.graph.run((
            "match (e:Employee)-[:WORKED_ON]->(p)-[:FOR_CLIENT]->(c) "
            "match (p)-[:ACCESSED_STEP]->(s) "
            "where c.company_id='%s' "
            "return s" % self.CLIENT_ID
        ))

        assert cursor.forward() == 1
        assert cursor.current()['s']['step_number'] == self.STEP_ACCESSED
        assert cursor.forward() == 0


class TestApplicationNode(object):

    @classmethod
    def setup_class(cls):

        cls.APP_1 = 'test-crm-app'
        cls.APP_2 = 'test-erp-app'
        cls.APP_3 = 'test-compliance-app'

        cls.app_1 = Application.push_crm(cls.APP_1)
        cls.app_2 = Application.push_erp(cls.APP_2)
        cls.app_3 = Application.push_compliance(cls.APP_3)

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (a:Application)"
            "delete a"
        ))

    def test_application_nodes(self, db):

        cursor = db.graph.run((
            "match (a:Application) "
            "return a"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['a']['name'] == self.APP_1
        assert cursor.forward() == 1
        assert cursor.current()['a']['name'] == self.APP_2
        assert cursor.forward() == 1
        assert cursor.current()['a']['name'] == self.APP_3
        assert cursor.forward() == 0

    def test_crm_label(self, db):

        cursor = db.graph.run((
            "match (a:Crm) "
            "return a"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['a']['name'] == self.APP_1
        assert cursor.forward() == 0

    def test_cloud_label(self, db):

        cursor = db.graph.run((
            "match (a:Cloud) "
            "return a"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['a']['name'] == self.APP_1
        assert cursor.forward() == 0

    def test_erp_label(self, db):

        cursor = db.graph.run((
            "match (a:Erp) "
            "return a"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['a']['name'] == self.APP_2
        assert cursor.forward() == 0

    def test_compliance_label(self, db):

        cursor = db.graph.run((
            "match (a:Compliance) "
            "return a"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['a']['name'] == self.APP_3
        assert cursor.forward() == 0


class TestDatabaseNode(object):

    @classmethod
    def setup_class(cls):

        cls.TYPE = 'sql'
        cls.database = Database.push(cls.TYPE)

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (d:Database)"
            "delete d"
        ))

    def test_database_node(self, db):

        cursor = db.graph.run((
            "match (d:Database) "
            "return d"
        ))

        assert cursor.forward() == 1
        assert cursor.current()['d']['type'] == self.TYPE
        assert cursor.forward() == 0


class TestBuildCrmDatabase(object):

    @classmethod
    def setup_class(cls):

        cls.APP_NAME = 'some crm app'
        cls.TYPE = 'sql'
        cls.crm_db = BuildCrmDatabase(cls.APP_NAME, cls.TYPE)
        cls.crm_db.build()

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (a:Application), (d:Database) "
            "detach delete a, d"
        ))

    def test_crm_database_structure(self, db):

        cursor = db.graph.run((
            "match (:Application)-[:USES_DATABASE]->(db) "
            "return db"
        ))

        assert cursor.forward() == 1
        assert isinstance(cursor.current()['db'], Node)
        assert cursor.current()['db']['type'] == self.TYPE
        assert cursor.forward() == 0


class TestBuildErpDatabase(object):

    @classmethod
    def setup_class(cls):

        cls.APP_NAME = 'some erp app'
        cls.TYPE = 'graphdb'
        cls.erp_db = BuildErpDatabase(cls.APP_NAME, cls.TYPE)
        cls.erp_db.build()

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (a:Application), (d:Database) "
            "detach delete a, d"
        ))

    def test_erp_database_structure(self, db):

        cursor = db.graph.run((
            "match (:Application)-[:USES_DATABASE]->(db) "
            "return db"
        ))

        assert cursor.forward() == 1
        assert isinstance(cursor.current()['db'], Node)
        assert cursor.current()['db']['type'] == self.TYPE
        assert cursor.forward() == 0


class TestBuildComplianceDatabase(object):

    @classmethod
    def setup_class(cls):

        cls.APP_NAME = 'some compliance app'
        cls.TYPE = 'mysql'
        cls.compliance_db = BuildComplianceDatabase(cls.APP_NAME, cls.TYPE)
        cls.compliance_db.build()

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (a:Application), (d:Database) "
            "detach delete a, d"
        ))

    def test_compliance_database_structure(self, db):

        cursor = db.graph.run((
            "match (:Application)-[:USES_DATABASE]->(db) "
            "return db"
        ))

        assert cursor.forward() == 1
        assert isinstance(cursor.current()['db'], Node)
        assert cursor.current()['db']['type'] == self.TYPE
        assert cursor.forward() == 0


class TestEmployeeAppAccess(object):

    @classmethod
    def setup_class(cls):

        cls.ID = '1122452335'
        cls.EMAIL = 'gpwn@fuzz.org'
        cls.employee = Employee()
        cls.employee.push(cls.ID, cls.EMAIL)

        cls.APP_1 = 'test-crm-app'
        cls.app_1 = Application.push_crm(cls.APP_1)

        cls.employee_app_access = EmployeeAppAccess('Crm', cls.ID)
        cls.employee_app_access.build()

    @classmethod
    def teardown_class(cls):
        _db.graph.run((
            "match (n) "
            "detach delete n"
        ))

    def test_compliance_database_structure(self, db):

        cursor = db.graph.run((
            "match (:Employee)-[:HAS_ACCESS_TO]->(app) "
            "return app"
        ))

        assert cursor.forward() == 1
        assert isinstance(cursor.current()['app'], Node)
        assert cursor.forward() == 0