import json

from ngi_pipeline.conductor.classes import NGIProject
from ngi_pipeline.database.communicate import get_project_id_from_name
from ngi_pipeline.database.session import construct_charon_url, get_charon_session

def test_get_project_id_from_name():
    # Create a project with a known project ID
    project_id = "P100000"
    data = dict(projectid=project_id, name='P.Mayhem_13_01')
    session = get_charon_session()
    response = session.post(construct_charon_url('project'),
                            data=json.dumps(data))
    try:
        assert response.status_code == 201, response
        project = response.json()
        # Check that it matches
        assert project['projectid'] == project_id, "Project ID is incorrect"
    finally:
        # Remove the project
        response = session.delete(construct_charon_url('project', project_id))
        assert response.status_code == 204, response
        assert len(response.content) == 0, 'no content in response'

def test_rebuild_project_obj_from_Charon():
    # Create fake project / sample / libprep / seqrun
    pass