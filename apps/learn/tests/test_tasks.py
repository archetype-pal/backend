from apps.learn.tasks import answer_question, write_lesson
from config.celery import app


def test_lessons_run_on_their_own_queue():
    for task in (write_lesson, answer_question):
        assert app.amqp.router.route({}, task.name)["queue"].name == "learn"
