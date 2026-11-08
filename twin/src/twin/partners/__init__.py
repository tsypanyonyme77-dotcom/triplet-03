"""Adapters between the Twin and its partners. Nothing here simulates: each module turns the Twin's own
readings, topology and actuator calls into a partner's messages and back.

  reading_log       readings by cursor, for a partner that polls (the City Brain's list_readings)
  topology          zones, adjacency, exits, facilities (stations, pumps) and sensors, in the City Brain's shape
  incident_links    a partner's incident id <-> the Twin's call-centre incident, and which unit went for which
  brain_calls       the City Brain's signed actuator calls: check the signature, translate, answer in its shape
  brain_http        the City Brain's plain HTTP routes (GET /readings, /topology, /capabilities, POST /actuators/{action})
  brain_mcp         the same operations as MCP tools, at /mcp
  guardian_dialect  a reading in the Guardian's contract 1.0
  guardian_push     batches of those readings pushed to the Guardian (POST /v1/readings)
  guardian_tools    the calls the Guardian forwards (POST /tools/{action}), answered in its shape
"""
