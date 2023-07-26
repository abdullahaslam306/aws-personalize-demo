exports.handler = async (event) => {
    return {"items": [event.userId, 100, 200, 300, 400]};
};