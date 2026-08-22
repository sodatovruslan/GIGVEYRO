export class AuthOperationGate {
  private operation = 0;
  private sessionController: AbortController | null = null;

  startSession() {
    const id = ++this.operation;
    this.sessionController?.abort();
    const controller = new AbortController();
    this.sessionController = controller;
    return { id, controller };
  }

  startExclusive() {
    const id = ++this.operation;
    this.sessionController?.abort();
    this.sessionController = null;
    return id;
  }

  isCurrent(id: number) { return id === this.operation; }

  finishSession(controller: AbortController) {
    if (this.sessionController === controller) this.sessionController = null;
  }

  cancel() { this.startExclusive(); }
}
